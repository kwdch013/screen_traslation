"""固定画像のframe組み立てと契約照合付きの受信(標準ライブラリとjsonschemaだけに依存する軽い部品)。

プロセス内の実エンジン結合試験(pipeline_support)と、ホストから実コンテナへ接続する
試験(server/tests/container)が同じ実装を共有する。エンジンやサーバー本体はimportしない。
"""

from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
import re
import struct
import time
from typing import Any
import unicodedata

from jsonschema import Draft202012Validator, FormatChecker

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/pipeline"
CONTRACTS = next(
	parent / "contracts" for parent in Path(__file__).resolve().parents
	if (parent / "contracts/schemas/stream-message.schema.json").is_file()
)
JAPANESE = re.compile(r"[぀-ヿ㐀-鿿]")


def load_cases() -> list[dict[str, Any]]:
	return json.loads((FIXTURES / "cases.json").read_text(encoding="utf-8"))


def case_image(case: dict[str, Any]) -> bytes:
	return (FIXTURES / case["file"]).read_bytes()


def normalize(text: str) -> str:
	"""acceptance.mdのOCR評価と同じ正規化(NFC・連続空白の単一化・前後空白除去)。"""
	return " ".join(unicodedata.normalize("NFC", text).split())


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


def read_until(
	websocket: Any,
	predicate: Callable[[dict[str, Any]], bool],
	*,
	timeout: float = 120,
	overall_timeout: float = 180,
	clock: Callable[[], float] = time.monotonic,
) -> list[dict[str, Any]]:
	"""契約に照合しながら、条件に合うtext messageまでを順に集める。

	timeoutは1回のrecv、overall_timeoutはこの呼び出し全体の上限。heartbeat等が続いて
	条件に合わない場合でも、全体の期限で失敗するため試験が長時間ハングしない(いずれも合否の同期条件ではない)。
	"""
	messages: list[dict[str, Any]] = []
	deadline = clock() + overall_timeout
	while True:
		remaining = deadline - clock()
		if remaining <= 0:
			raise TimeoutError(f"{overall_timeout}秒以内に期待するmessageが届きませんでした。受信済み: {[m['type'] for m in messages]}")
		message = json.loads(websocket.recv(timeout=min(timeout, remaining)))
		_VALIDATOR.validate(message)
		messages.append(message)
		if predicate(message):
			return messages


def is_result(frame_id: int) -> Callable[[dict[str, Any]], bool]:
	return lambda message: message["type"] == "result" and message["frame_id"] == frame_id
