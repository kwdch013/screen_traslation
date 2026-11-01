"""実エンジン結合試験の共通部品(モデル確認・固定画像・計測・同期用の道具)。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
import importlib.metadata
import os
from pathlib import Path
import threading
from typing import Any

from app.contracts import Frame, Rect, TextRegion
from frame_support import (  # noqa: F401  既存importを保つため再公開する
	CONTRACTS, FIXTURES, JAPANESE, case_image, frame_message, is_result, load_cases, normalize, read_until,
)
from prepare_model import STANZA_MANIFEST_PATH, load_manifest
from screen_translation_server.engines.lifecycle import ModelManifest
from screen_translation_server.engines.stanza_resources import StanzaResourceError, StanzaResources
from screen_translation_server.startup import load_stanza_resources

PREPARE_HINT = (
	"Argosモデルが未準備です。次を実行してから再試験してください(外向き通信が必要・初回のみ約20秒): "
	"docker compose -f server/compose.test.yml --profile model run --build --rm prepare-model"
)


def model_directory() -> Path:
	return Path(os.environ.get("SCREEN_TRANSLATION_TEST_MODEL_DIR", "/models"))


def require_model(manifest: ModelManifest | None = None) -> ModelManifest:
	"""必須試験はモデル未準備をskipで合格扱いにせず、準備手順付きで失敗させる。"""
	manifest = manifest or load_manifest()
	from argostranslate import settings

	model = model_directory() / f"translate-en_ja-{manifest.version}.argosmodel"
	installed = any(settings.package_data_dir.glob("en_ja"))
	if not model.is_file() or not installed:
		raise AssertionError(PREPARE_HINT)
	try:
		stanza_resources().verify()
	except StanzaResourceError as error:
		raise AssertionError(f"{error} {PREPARE_HINT}") from None
	return manifest


def stanza_resources() -> StanzaResources:
	"""製品と同じmanifest検証でStanza資源を確認する。未準備・破損は準備手順付きで失敗させる。"""
	return load_stanza_resources(STANZA_MANIFEST_PATH)


def engine_versions(manifest: ModelManifest) -> dict[str, str]:
	"""結果の再現に必要なエンジン・モデルの版を集める。"""
	import pytesseract
	from argostranslate import package

	installed = [p for p in package.get_installed_packages() if (p.from_code, p.to_code) == ("en", "ja")]
	versions = {"tesseract": str(pytesseract.get_tesseract_version())}
	for name in ("pytesseract", "argostranslate", "ctranslate2", "stanza", "pillow"):
		versions[name] = importlib.metadata.version(name)
	versions["argos_model_manifest"] = manifest.version
	versions["argos_model_installed"] = ",".join(sorted(str(p.package_version) for p in installed))
	return versions


def edit_distance(expected: str, actual: str) -> int:
	previous = list(range(len(actual) + 1))
	for row, left in enumerate(expected, start=1):
		current = [row]
		for column, right in enumerate(actual, start=1):
			current.append(min(previous[column] + 1, current[-1] + 1, previous[column - 1] + (left != right)))
		previous = current
	return previous[-1]


def character_error_rate(pairs: Sequence[tuple[str, str]]) -> float:
	"""群の総編集距離/正解文字数。無出力は削除として数える。"""
	expected_total = sum(len(normalize(expected)) for expected, _ in pairs)
	distance = sum(edit_distance(normalize(expected), normalize(actual)) for expected, actual in pairs)
	return distance / expected_total


class GatedOcr:
	"""実OCRを包み、最初の呼び出しを`release`されるまで保留する。

	同期はEventだけで行い、保留中に後続frameを待機枠へ入れる状況を時間に頼らず作る。
	"""

	def __init__(self, ocr: Any, *, gate_first_calls: int = 1) -> None:
		self._ocr = ocr
		self._remaining = gate_first_calls
		self._lock = threading.Lock()
		self.started = threading.Event()
		self.release = threading.Event()
		self.calls = 0

	def recognize(self, frame: Frame) -> Sequence[TextRegion]:
		with self._lock:
			self.calls += 1
			gated = self._remaining > 0
			self._remaining -= int(gated)
		if gated:
			self.started.set()
			if not self.release.wait(timeout=120):
				raise TimeoutError("保留した実OCRが解放されませんでした。")
		return self._ocr.recognize(frame)

	def validate(self) -> None:
		self._ocr.validate()


class UnpositionedOcr:
	"""実OCRの文字はそのまま、位置だけを不明または画像外にして返す(位置不明の契約確認用)。"""

	def __init__(self, ocr: Any, mode: str) -> None:
		self._ocr = ocr
		self._mode = mode

	def recognize(self, frame: Frame) -> Sequence[TextRegion]:
		regions = self._ocr.recognize(frame)
		if self._mode == "unavailable":
			return [replace(region, positioning="unavailable") for region in regions]
		return [replace(region, bounds=Rect(region.bounds.x + 100000, region.bounds.y, region.bounds.width,
			region.bounds.height)) for region in regions]


class DropRecorder:
	"""pipelineの破棄通知を数え、指定件数に達するまで待てる観測器。"""

	def __init__(self) -> None:
		self._condition = threading.Condition()
		self.counts: dict[str, int] = {}

	def dropped(self, stage: str, correlation_id: str = "") -> None:
		with self._condition:
			self.counts[stage] = self.counts.get(stage, 0) + 1
			self._condition.notify_all()

	def finish(self, *_args: object, **_kwargs: object) -> None:
		return None

	def wait_for(self, stage: str, count: int, timeout: float = 120) -> bool:
		with self._condition:
			return self._condition.wait_for(lambda: self.counts.get(stage, 0) >= count, timeout)
