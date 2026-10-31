"""実エンジン結合試験の共通部品(モデル確認・固定画像・計測・同期用の道具)。"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
import importlib.metadata
import json
import os
from pathlib import Path
import re
import struct
import threading
import unicodedata
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from app.contracts import Frame, Rect, TextRegion
from prepare_model import load_manifest
from screen_translation_server.engines.lifecycle import ModelManifest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/pipeline"
CONTRACTS = next(
	parent / "contracts" for parent in Path(__file__).resolve().parents
	if (parent / "contracts/schemas/stream-message.schema.json").is_file()
)
JAPANESE = re.compile(r"[぀-ヿ㐀-鿿]")
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
	return manifest


def use_installed_stanza_resources() -> None:
	"""Stanzaの資源一覧取得(既定は毎回外部取得)を止め、導入済み資源だけを使う。

	結合試験コンテナは外向き通信を持たないため。製品側が同じ外部取得を行う点は
	docs/v1.0/testing.mdの「未解決事項」に記録している。
	"""
	import stanza

	if getattr(stanza.Pipeline, "_reuse_installed_resources", False):
		return

	class ReusePipeline(stanza.Pipeline):  # type: ignore[misc, name-defined]
		_reuse_installed_resources = True

		def __init__(self, *args: Any, **kwargs: Any) -> None:
			kwargs.setdefault("download_method", "reuse_resources")
			super().__init__(*args, **kwargs)

	stanza.Pipeline = ReusePipeline


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


def load_cases() -> list[dict[str, Any]]:
	return json.loads((FIXTURES / "cases.json").read_text(encoding="utf-8"))


def case_image(case: dict[str, Any]) -> bytes:
	return (FIXTURES / case["file"]).read_bytes()


def normalize(text: str) -> str:
	"""acceptance.mdのOCR評価と同じ正規化(NFC・連続空白の単一化・前後空白除去)。"""
	return " ".join(unicodedata.normalize("NFC", text).split())


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


def frame_message(session: dict[str, Any], frame_id: int, case: dict[str, Any], image: bytes | None = None) -> bytes:
	"""契約のSTF1バイナリframeを組み立てる。"""
	image = image if image is not None else case_image(case)
	metadata = json.dumps({
		"contract_version": 1, "session_id": session["session_id"],
		"generation": session["generation"], "frame_id": frame_id,
		"dictionary_revision": session["dictionary_revision"],
		"image_width": case["width"], "image_height": case["height"],
		"content_type": "image/png", "image_length": len(image),
	}, separators=(",", ":")).encode()
	return b"STF1" + struct.pack(">I", len(metadata)) + metadata + image


_VALIDATOR = Draft202012Validator(
	json.loads((CONTRACTS / "schemas/stream-message.schema.json").read_text(encoding="utf-8")),
	format_checker=FormatChecker(),
)


def read_until(websocket: Any, predicate: Callable[[dict[str, Any]], bool], *, timeout: float = 120) -> list[dict[str, Any]]:
	"""契約に照合しながら、条件に合うtext messageまでを順に集める。timeoutは無応答検出専用。"""
	messages: list[dict[str, Any]] = []
	while True:
		message = json.loads(websocket.recv(timeout=timeout))
		_VALIDATOR.validate(message)
		messages.append(message)
		if predicate(message):
			return messages


def is_result(frame_id: int) -> Callable[[dict[str, Any]], bool]:
	return lambda message: message["type"] == "result" and message["frame_id"] == frame_id


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
