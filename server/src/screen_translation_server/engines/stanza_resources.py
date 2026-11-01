"""Stanzaの資源(resources.jsonと使用言語のモデル)を準備段階で取得・検証する。

実行時は外向き通信を行わない(stanza_offline.py)ため、資源は準備段階で固定manifestの
サイズ・SHA-256を検証して永続領域へ置く。実行時の準備(EngineLifecycle)は同じmanifestで再検証し、
未準備・破損なら準備失敗としてreadinessへ反映する。エラー文言にパス・URLは含めない。
"""

from __future__ import annotations

import hashlib
import os
import re
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

MAX_FILE_BYTES = 512 * 1024**2
PREPARATION_TIMEOUT_SECONDS = 600
_FIELDS = ("path", "url", "size_bytes", "sha256")


class StanzaResourceError(Exception):
	"""Stanza資源の未準備・破損・取得失敗。メッセージは利用者へ見せてよい固定文だけにする。"""


@dataclass(frozen=True)
class StanzaFile:
	path: str
	url: str
	size_bytes: int
	sha256: str


@dataclass(frozen=True)
class StanzaManifest:
	"""取得するStanza資源の一覧。値は取得元から観測したもので、配布元が保証する信頼済みdigestではない。"""

	version: str
	files: tuple[StanzaFile, ...]

	def validate(self) -> None:
		if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}", self.version):
			raise ValueError("Stanza資源の版の形式が不正です。")
		if not self.files:
			raise ValueError("Stanza資源が1つも指定されていません。")
		seen: set[str] = set()
		for file in self.files:
			parsed = urlsplit(file.url)
			if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None:
				raise ValueError("Stanza資源の取得先にはHTTPS URLが必要です。")
			path = PurePosixPath(file.path)
			if not file.path or path.is_absolute() or ".." in path.parts or "\\" in file.path or file.path in seen:
				raise ValueError("Stanza資源の配置先が不正または重複しています。")
			seen.add(file.path)
			if not 1 <= file.size_bytes < MAX_FILE_BYTES:
				raise ValueError("Stanza資源のサイズが範囲外です。")
			if not re.fullmatch(r"[0-9a-fA-F]{64}", file.sha256):
				raise ValueError("Stanza資源に信頼済みSHA-256が必要です。")

	@classmethod
	def from_json(cls, data: Mapping[str, Any]) -> StanzaManifest:
		if set(data) != {"version", "files"}:
			raise ValueError("Stanza manifestの項目が不正です。")
		entries = data["files"]
		if not isinstance(entries, list) or any(not isinstance(e, dict) or set(e) != set(_FIELDS) for e in entries):
			raise ValueError("Stanza manifestのfilesが不正です。")
		return cls(version=data["version"], files=tuple(StanzaFile(**entry) for entry in entries))


def argos_stanza_directory(
	from_code: str = "en",
	to_code: str = "ja",
	*,
	installed_packages: Callable[[], Iterable[Any]] | None = None,
) -> Path:
	"""Argosが文分割用にStanza資源を探す場所(導入済みパッケージ配下のstanza)を返す。"""
	if installed_packages is None:
		from argostranslate import package

		installed_packages = package.get_installed_packages
	for installed in installed_packages():
		if (installed.from_code, installed.to_code) == (from_code, to_code):
			return Path(installed.package_path) / "stanza"
	raise StanzaResourceError("Argos Translateの翻訳パッケージが未導入のため、Stanza資源の場所を決められません。")


class StanzaResources:
	"""manifestどおりの資源が置かれているかを検証し、足りない・壊れた分だけ取得する。"""

	def __init__(
		self,
		manifest: StanzaManifest,
		directory: Callable[[], Path],
		*,
		monotonic: Callable[[], float] = time.monotonic,
	) -> None:
		self.manifest = manifest
		self._directory = directory
		self._monotonic = monotonic

	def verify(self) -> None:
		"""全資源がmanifestと一致することを確認する。実行時の準備で毎回行う(合計数MiBで軽い)。"""
		root = self._directory()
		missing = False
		for file in self.manifest.files:
			status = _status(root / file.path, file)
			if status == "corrupt":
				raise StanzaResourceError("Stanza資源が破損しています(サイズまたはSHA-256がmanifestと一致しません)。管理者が資源準備を再実行してください。")
			missing = missing or status == "missing"
		if missing:
			raise StanzaResourceError("Stanza資源が未準備です。管理者が資源準備を実行してください。")

	def provision(
		self,
		*,
		downloader: Callable[[str, Path, float], None] | None = None,
		timeout_seconds: float = PREPARATION_TIMEOUT_SECONDS,
	) -> None:
		"""未準備・破損の資源だけ取得し、検証に通ったものだけを配置する。外向き通信が必要な準備専用の処理。"""
		if downloader is None:
			from screen_translation_server.engines.lifecycle import _download

			downloader = _download
		try:
			self.manifest.validate()
		except ValueError as error:
			raise StanzaResourceError(str(error)) from None
		deadline = self._monotonic() + timeout_seconds
		root = self._directory()
		for file in self.manifest.files:
			target = root / file.path
			if _status(target, file) == "valid":
				continue
			remaining = deadline - self._monotonic()
			if remaining <= 0:
				raise StanzaResourceError("Stanza資源の準備期限を超過しました。")
			target.parent.mkdir(parents=True, exist_ok=True)
			staging = target.with_name(f".{target.name}.part")
			try:
				downloader(file.url, staging, remaining)
				if _status(staging, file) != "valid":
					raise StanzaResourceError("取得したStanza資源がmanifestのサイズまたはSHA-256と一致しません。")
				os.replace(staging, target)
			except StanzaResourceError:
				raise
			except Exception as error:
				raise StanzaResourceError(f"Stanza資源を取得できませんでした ({type(error).__name__})。") from None
			finally:
				staging.unlink(missing_ok=True)


def _status(path: Path, file: StanzaFile) -> str:
	"""`valid` / `missing` / `corrupt`。サイズが合わない場合はハッシュ計算を省く。"""
	try:
		if not path.is_file():
			return "missing"
		if path.stat().st_size != file.size_bytes:
			return "corrupt"
		digest = hashlib.sha256()
		with path.open("rb") as stream:
			for chunk in iter(lambda: stream.read(1024**2), b""):
				digest.update(chunk)
	except OSError:
		return "corrupt"
	return "valid" if digest.hexdigest().lower() == file.sha256.lower() else "corrupt"
