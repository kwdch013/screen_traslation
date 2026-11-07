"""manifestと取得元の差分確認コマンド。`python -m screen_translation_server.manifest_check`。

Argosモデルとstanza資源のmanifest(サイズ・SHA-256・URL)を取得元から再取得した観測値と比較し、
差分を報告して終了コードで返す。読み取り専用で、manifestは書き換えない(更新は人が差分を確認して行う)。
外部へ通信するのはこのコマンドの実行時だけで、CIやサーバー実行時には使わない。
終了コード: 0=全件一致 / 1=差分あり / 2=設定エラー / 3=取得できず確認不能(差分なし)。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from screen_translation_server.engines.lifecycle import ModelManifest
from screen_translation_server.engines.stanza_resources import StanzaManifest
from screen_translation_server.startup import MANIFEST_VARIABLE, STANZA_MANIFEST_VARIABLE

MAX_BYTES = 1024**3
FETCH_TIMEOUT_SECONDS = 1800


class ManifestCheckError(Exception):
	"""manifestを読めない・不正。メッセージにパス・内容は含めない。"""


@dataclass(frozen=True)
class Observation:
	size_bytes: int
	sha256: str
	final_url: str | None = None


@dataclass(frozen=True)
class Entry:
	label: str
	url: str
	size_bytes: int
	sha256: str


@dataclass(frozen=True)
class Result:
	label: str
	url: str
	status: str  # match / changed / error
	differences: tuple[str, ...]
	observed: Observation | None


Fetcher = Callable[[str, float], Observation]


def entries_from_manifests(model: Mapping[str, Any], stanza: Mapping[str, Any]) -> list[Entry]:
	try:
		argos = ModelManifest(**model)
		files = StanzaManifest.from_json(stanza)
		files.validate()
	except (ValueError, TypeError) as error:
		raise ManifestCheckError(f"manifestの形式が不正です ({type(error).__name__})。") from None
	entries = [Entry(f"argos:{argos.version}", argos.source_url, argos.size_bytes, argos.sha256)]
	entries += [Entry(f"stanza:{files.version}:{f.path}", f.url, f.size_bytes, f.sha256) for f in files.files]
	return entries


def entries_from_files(model_path: Path, stanza_path: Path) -> list[Entry]:
	try:
		model = json.loads(Path(model_path).read_text(encoding="utf-8"))
		stanza = json.loads(Path(stanza_path).read_text(encoding="utf-8"))
	except (OSError, ValueError) as error:
		raise ManifestCheckError(f"manifestを読み込めません ({type(error).__name__})。") from None
	return entries_from_manifests(model, stanza)


def fetch_observation(
	url: str,
	timeout_seconds: float,
	*,
	opener: Callable[..., Any] = urllib.request.urlopen,
	max_bytes: int = MAX_BYTES,
	monotonic: Callable[[], float] = time.monotonic,
) -> Observation:
	"""取得元から本体を読み、サイズとSHA-256を計算する(保存はしない)。"""
	if urlsplit(url).scheme != "https":
		raise ValueError("取得先にはHTTPS URLが必要です。")
	request = urllib.request.Request(url, headers={"User-Agent": "screen-translation-manifest-check/1"})
	started = monotonic()
	digest = hashlib.sha256()
	size = 0
	with opener(request, timeout=min(timeout_seconds, FETCH_TIMEOUT_SECONDS)) as response:
		final_url = response.geturl()
		while chunk := response.read(1024**2):
			if monotonic() - started > timeout_seconds:
				raise TimeoutError("取得が期限を超過しました。")
			size += len(chunk)
			if size > max_bytes:
				raise ValueError("取得サイズが上限を超えました。")
			digest.update(chunk)
	return Observation(size, digest.hexdigest(), final_url)


def check_entries(entries: Sequence[Entry], fetcher: Fetcher, timeout_seconds: float = FETCH_TIMEOUT_SECONDS) -> list[Result]:
	results = []
	for entry in entries:
		try:
			observed = fetcher(entry.url, timeout_seconds)
		except Exception as error:
			# 例外の詳細にはパスや取得先が含まれ得るため、型名だけを残す。
			results.append(Result(entry.label, entry.url, "error", (f"fetch_failed:{type(error).__name__}",), None))
			continue
		differences = []
		if observed.size_bytes != entry.size_bytes:
			differences.append("size_bytes")
		if observed.sha256.lower() != entry.sha256.lower():
			differences.append("sha256")
		if observed.final_url:
			final = urlsplit(observed.final_url)
			# CDNへのHTTPSリダイレクトは配布元の通常動作なので差分にしない。HTTPSから外れた場合だけ差分とする。
			if final.scheme != "https":
				differences.append("redirect_not_https")
		results.append(Result(entry.label, entry.url, "changed" if differences else "match", tuple(differences), observed))
	return results


def exit_code(results: Sequence[Result]) -> int:
	if any(r.status == "changed" for r in results):
		return 1
	if any(r.status == "error" for r in results):
		return 3
	return 0


def format_report(results: Sequence[Result]) -> str:
	lines = []
	for r in results:
		if r.status == "match":
			lines.append(f"一致: {r.label}")
		elif r.status == "error":
			lines.append(f"確認不能: {r.label} ({r.differences[0]}) {r.url}")
		else:
			lines.append(f"差分あり: {r.label} [{', '.join(r.differences)}] {r.url}")
			if r.observed:
				lines.append(f"  観測値: size_bytes={r.observed.size_bytes} sha256={r.observed.sha256}")
	matched = sum(r.status == "match" for r in results)
	lines.append(f"{len(results)}件中 {matched}件一致 / 差分 {sum(r.status == 'changed' for r in results)}件 / 確認不能 {sum(r.status == 'error' for r in results)}件")
	lines.append("manifestは自動更新しません。差分は人が取得元・ライセンスを確認してから docs/v1.0/operations.md の手順で更新してください。")
	return "\n".join(lines)


def main(
	argv: Sequence[str] | None = None,
	*,
	environment: Mapping[str, str] | None = None,
	fetcher: Fetcher | None = None,
) -> int:
	env = os.environ if environment is None else environment
	parser = argparse.ArgumentParser(prog="manifest_check", description="manifestと取得元の差分を確認する(読み取り専用)")
	parser.add_argument("--model-manifest", default=env.get(MANIFEST_VARIABLE))
	parser.add_argument("--stanza-manifest", default=env.get(STANZA_MANIFEST_VARIABLE))
	parser.add_argument("--target", choices=("all", "argos", "stanza"), default="all")
	args = parser.parse_args(argv)
	if not args.model_manifest or not args.stanza_manifest:
		print(f"--model-manifest / --stanza-manifest か環境変数 {MANIFEST_VARIABLE} / {STANZA_MANIFEST_VARIABLE} でmanifestを指定してください。", file=sys.stderr)
		return 2
	try:
		entries = entries_from_files(args.model_manifest, args.stanza_manifest)
	except ManifestCheckError as error:
		print(error, file=sys.stderr)
		return 2
	if args.target != "all":
		entries = [e for e in entries if e.label.startswith(f"{args.target}:")]
	results = check_entries(entries, fetcher or fetch_observation)
	print(format_report(results))
	return exit_code(results)


if __name__ == "__main__":
	raise SystemExit(main())
