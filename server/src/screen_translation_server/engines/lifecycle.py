"""モデル導入とOCR/翻訳エンジンの準備状態を管理する。"""

from __future__ import annotations

import hashlib
import os
import re
import threading
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any, Callable, cast
from urllib.parse import urlsplit


MAX_MODEL_BYTES = 1024**3
PREPARATION_TIMEOUT_SECONDS = 1800
INSTALLED_START_TIMEOUT_SECONDS = 120
class ModelState(StrEnum):
	MISSING = "missing"
	PREPARING = "preparing"
	READY = "ready"
	FAILED = "failed"


@dataclass(frozen=True)
class ModelManifest:
	version: str
	source_url: str
	size_bytes: int
	sha256: str
	license_name: str
	license_url: str
	license_accepted: bool

	def validate(self) -> None:
		if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}", self.version):
			raise ValueError("モデル版の形式が不正です。")
		if not _is_https_url(self.source_url) or not _is_https_url(self.license_url):
			raise ValueError("モデルとライセンスの取得先にはHTTPS URLが必要です。")
		if not 1 <= self.size_bytes <= MAX_MODEL_BYTES:
			raise ValueError("モデルサイズは1 GiB以下で指定してください。")
		if not re.fullmatch(r"[0-9a-fA-F]{64}", self.sha256):
			raise ValueError("信頼済みSHA-256が必要です。")
		if not self.license_name.strip() or not self.license_accepted:
			raise ValueError("モデルライセンスの確認と同意が必要です。")


class ModelProvisioner:
	"""明示されたmanifestだけを取得し、検証後にエンジンへ導入する。"""

	def __init__(
		self,
		manifest: ModelManifest,
		destination: Path,
		*,
		downloader: Callable[[str, Path, float], None] | None = None,
		installer: Callable[[Path], None] | None = None,
		progress: Callable[[str], None] | None = None,
		monotonic: Callable[[], float] = time.monotonic,
	) -> None:
		self.manifest = manifest
		self.destination = destination
		self._downloader = downloader or _download
		self._installer = installer or _install_argos_model
		self._progress = progress or (lambda _stage: None)
		self._monotonic = monotonic
		self.progress = "missing"
		self.failure_reason: str | None = None

	@property
	def model_path(self) -> Path:
		return self.destination / f"translate-en_ja-{self.manifest.version}.argosmodel"

	def provision(
		self,
		timeout_seconds: float = PREPARATION_TIMEOUT_SECONDS,
		*,
		deadline: float | None = None,
	) -> Path:
		try:
			if timeout_seconds <= 0:
				raise ValueError("モデル準備の期限は正数で指定してください。")
			timeout_seconds = min(timeout_seconds, PREPARATION_TIMEOUT_SECONDS)
			deadline = min(deadline, self._monotonic() + timeout_seconds) if deadline is not None else None
			if deadline is None:
				deadline = self._monotonic() + timeout_seconds
			self._check_deadline(deadline)
			self.manifest.validate()
			self._check_deadline(deadline)
			self.destination.mkdir(parents=True, exist_ok=True)
			if self.model_path.exists():
				self._check_deadline(deadline)
				self._verify(self.model_path)
				self._check_deadline(deadline)
				self._set_progress("installing")
				self._installer(self.model_path)
				self._check_deadline(deadline)
				self._set_progress("complete")
				return self.model_path

			staging = self.destination / f".{self.model_path.name}.part"
			self._set_progress("downloading")
			self._downloader(self.manifest.source_url, staging, max(0.0, deadline - self._monotonic()))
			self._check_deadline(deadline)
			self._set_progress("verifying")
			self._verify(staging)
			self._check_deadline(deadline)
			_validate_archive(staging)
			self._check_deadline(deadline)
			os.replace(staging, self.model_path)
			self._check_deadline(deadline)
			self._set_progress("installing")
			self._installer(self.model_path)
			self._check_deadline(deadline)
			self._set_progress("complete")
			return self.model_path
		except Exception as error:
			self.progress = "failed"
			self.failure_reason = _safe_failure_reason(error)
			self._progress(self.progress)
			if "staging" in locals():
				staging.unlink(missing_ok=True)
			raise

	def _check_deadline(self, deadline: float) -> None:
		if self._monotonic() >= deadline:
			raise TimeoutError("モデル準備の期限を超過しました。")

	def _set_progress(self, stage: str) -> None:
		self.progress = stage
		self._progress(stage)

	def _verify(self, path: Path) -> None:
		if path.stat().st_size != self.manifest.size_bytes:
			raise ValueError("モデルサイズがmanifestと一致しません。")
		digest_builder = hashlib.sha256()
		with path.open("rb") as model_file:
			for chunk in iter(lambda: model_file.read(1024**2), b""):
				digest_builder.update(chunk)
		digest = digest_builder.hexdigest()
		if digest.lower() != self.manifest.sha256.lower():
			raise ValueError("モデルSHA-256がmanifestと一致しません。")


@dataclass(frozen=True)
class ResourceLimits:
	max_cpu_cores: float = 2.0
	max_memory_bytes: int = 4 * 1024**3
	max_concurrent: int = 1
	max_waiting: int = 1

	def validate(self, cpu_count: float, memory_bytes: int) -> bool:
		return (
			0 < self.max_cpu_cores <= 2
			and 0 < self.max_memory_bytes <= 4 * 1024**3
			and 0 < cpu_count <= self.max_cpu_cores
			and 0 < memory_bytes <= self.max_memory_bytes
			and self.max_concurrent == 1
			and self.max_waiting == 1
		)

	def validate_runtime(self, cgroup_root: Path = Path("/sys/fs/cgroup")) -> bool:
		cpu_count, memory_bytes = _read_cgroup_limits(cgroup_root)
		return cpu_count is not None and memory_bytes is not None and self.validate(cpu_count, memory_bytes)


class EngineLifecycle:
	"""livenessとモデル/エンジンreadinessを別々に保持する。"""

	def __init__(
		self,
		manifest: ModelManifest,
		model_directory: str | Path,
		*,
		engine_loader: Callable[[], object] | None = None,
		warmup: Callable[[object], None] | None = None,
		resource_limits: ResourceLimits | None = None,
		resource_check: Callable[[], bool] | None = None,
		monotonic: Callable[[], float] = time.monotonic,
	) -> None:
		self.manifest = manifest
		self.model_directory = Path(model_directory)
		self.engine_loader = engine_loader or _load_engines
		self.warmup = warmup or _warmup_engines
		self.resource_limits = resource_limits or ResourceLimits()
		self.resource_check = resource_check or self.resource_limits.validate_runtime
		self._monotonic = monotonic
		self.state = ModelState.MISSING
		self.progress = "missing"
		self.failure_reason: str | None = None
		self._engine: object | None = None
		self._lock = threading.Lock()

	def health_response(self) -> dict[str, str]:
		return {"status": "alive"}

	def ready_response(self) -> dict[str, bool]:
		return {"ready": self.state == ModelState.READY}

	def prepare(self, *, deadline: float | None = None) -> object:
		with self._lock:
			if self.state == ModelState.READY and self._engine is not None:
				return self._engine
			self.state = ModelState.PREPARING
			self.progress = "verifying"
			self.failure_reason = None
			started = self._monotonic()
			installed_deadline = started + INSTALLED_START_TIMEOUT_SECONDS
			deadline = min(deadline, installed_deadline) if deadline is not None else installed_deadline
			try:
				_check_deadline(self._monotonic, deadline)
				self.manifest.validate()
				_check_deadline(self._monotonic, deadline)
				model_path = self.model_directory / f"translate-en_ja-{self.manifest.version}.argosmodel"
				if not model_path.is_file():
					self.state = ModelState.MISSING
					self.progress = "missing"
					self.failure_reason = "モデルが未導入です。管理者がモデル準備を実行してください。"
					raise FileNotFoundError(self.failure_reason)
				ModelProvisioner(self.manifest, self.model_directory)._verify(model_path)
				_check_deadline(self._monotonic, deadline)
				if not self.resource_check():
					raise RuntimeError("サーバー資源上限を確認できないか、CPU/メモリ上限を超過しています。")
				_check_deadline(self._monotonic, deadline)
				self.progress = "loading"
				engine = self.engine_loader()
				_check_deadline(self._monotonic, deadline)
				self.progress = "warmup"
				self.warmup(engine)
				_check_deadline(self._monotonic, deadline)
				self._engine = engine
				self.state = ModelState.READY
				self.progress = "complete"
				return engine
			except Exception as error:
				if self.state != ModelState.MISSING:
					self.state = ModelState.FAILED
					self.progress = "failed"
					self.failure_reason = _safe_failure_reason(error)
				self._engine = None
				raise


class LatestFrameBuffer:
	"""処理中に届いた画像を最新1件だけ待機させる。"""

	def __init__(self) -> None:
		self._frame: object | None = None
		self._lock = threading.Lock()

	def submit(self, frame: object) -> None:
		with self._lock:
			self._frame = frame

	def take(self) -> object | None:
		with self._lock:
			frame, self._frame = self._frame, None
			return frame


class ProcessingGate:
	"""処理を1件に制限し、待機枠では最新フレームだけを保持する。"""

	def __init__(self) -> None:
		self._active = False
		self._lock = threading.Lock()
		self._waiting = LatestFrameBuffer()

	def try_acquire(self) -> bool:
		with self._lock:
			if self._active:
				return False
			self._active = True
			return True

	def submit(self, frame: object) -> bool:
		"""即時処理を開始した場合はTrue、待機枠へ入れた場合はFalse。"""
		with self._lock:
			if not self._active:
				self._active = True
				return True
			self._waiting.submit(frame)
			return False

	def release(self) -> object | None:
		"""完了後に次の処理対象を返す。待機が無い場合は枠を解放する。"""
		with self._lock:
			frame = self._waiting.take()
			if frame is None:
				self._active = False
			return frame


def _is_https_url(value: str) -> bool:
	parsed = urlsplit(value)
	return parsed.scheme == "https" and bool(parsed.hostname) and parsed.username is None and parsed.password is None


def _download(url: str, target: Path, timeout_seconds: float) -> None:
	request = urllib.request.Request(url, headers={"User-Agent": "screen-translation-model-provisioner/1"})
	started = time.monotonic()
	with urllib.request.urlopen(request, timeout=min(timeout_seconds, PREPARATION_TIMEOUT_SECONDS)) as response:
		if urlsplit(response.geturl()).scheme != "https":
			raise ValueError("モデル取得先がHTTPSから逸脱しました。")
		with target.open("wb") as output:
			content_length = response.headers.get("Content-Length")
			if content_length is not None and int(content_length) > MAX_MODEL_BYTES:
				raise ValueError("モデル取得サイズが1 GiBを超えています。")
			copied = 0
			while chunk := response.read(1024**2):
				if time.monotonic() - started > timeout_seconds:
					raise TimeoutError("モデル取得が準備期限を超過しました。")
				copied += len(chunk)
				if copied > MAX_MODEL_BYTES:
					raise ValueError("モデル取得サイズが1 GiBを超えています。")
				output.write(chunk)


def _validate_archive(path: Path) -> None:
	with zipfile.ZipFile(path) as archive:
		total_size = 0
		for entry in archive.infolist():
			name = PurePosixPath(entry.filename)
			if name.is_absolute() or ".." in name.parts or "\\" in entry.filename:
				raise ValueError("モデルアーカイブに不正な展開先があります。")
			if (entry.external_attr >> 16) & 0o170000 == 0o120000:
				raise ValueError("モデルアーカイブのシンボリックリンクは許可されません。")
			total_size += entry.file_size
			if total_size > MAX_MODEL_BYTES:
				raise ValueError("モデル展開サイズが1 GiBを超えています。")


def _install_argos_model(path: Path) -> None:
	from argostranslate import package

	package.install_from_path(str(path))


def _load_engines() -> object:
	from screen_translation_server.engines import build_engines

	return build_engines()


def _warmup_engines(engines: object) -> None:
	from app.contracts import Frame  # type: ignore[import-untyped]

	ocr, translator = cast(tuple[Any, Any], engines)
	validate = getattr(ocr, "validate", None)
	if validate is not None:
		validate()
	translator.translate("Hello")
	ocr.recognize(Frame(image=None, captured_at=time.monotonic()))


def _safe_failure_reason(error: Exception) -> str:
	message = str(error).strip()
	if not message or len(message) > 256 or "://" in message or any(
		marker in message.lower() for marker in ("token", "secret", "authorization", "password")
	):
		return f"モデル準備に失敗しました ({type(error).__name__})。"
	return message


def _check_deadline(monotonic: Callable[[], float], deadline: float) -> None:
	if monotonic() >= deadline:
		raise TimeoutError("モデル準備の期限を超過しました。")


def _read_cgroup_limits(root: Path) -> tuple[float | None, int | None]:
	try:
		cpu_max = (root / "cpu.max").read_text(encoding="ascii").split()
		memory_max = (root / "memory.max").read_text(encoding="ascii").strip()
		if len(cpu_max) != 2 or cpu_max[0] == "max" or memory_max == "max":
			return None, None
		cpu_count = int(cpu_max[0]) / int(cpu_max[1])
		memory_bytes = int(memory_max)
		return cpu_count, memory_bytes
	except (OSError, ValueError, ZeroDivisionError):
		return None, None
