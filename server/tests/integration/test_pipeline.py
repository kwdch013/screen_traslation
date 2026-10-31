"""固定画像を実Tesseract/Argosへ通し、画像から訳文までの結果をWSS契約で検証する。

モデルが未準備なら失敗する(skipで合格扱いにしない)。準備手順はpipeline_support.PREPARE_HINT。
"""

from __future__ import annotations

import hashlib
import json
import sys
import unittest

from screen_translation_server.engines.ocr_select import REGION_MIN_CONFIDENCE
from pipeline_case import PipelineCase, gated
from pipeline_support import (
	JAPANESE,
	DropRecorder,
	UnpositionedOcr,
	case_image,
	character_error_rate,
	frame_message,
	is_result,
	load_cases,
	read_until,
)

CLEAR_CER_LIMIT = 0.05  # requirements.md: 明瞭群 CER 5%以下
COMPLEX_CER_LIMIT = 0.15  # 同: 複雑背景群 15%以下(自作4枚の小標本。最終判定は#109の200枚)

COMPLEX_REGRESSION_LIMIT = 0.02  # 固定4枚の実測0.0%に対する悪化検出(要件値ではない)


class FixtureAndMetricTests(unittest.TestCase):
	def test_fixture_images_match_the_recorded_hashes(self) -> None:
		cases = load_cases()
		self.assertEqual({case["group"] for case in cases}, {"clear", "complex", "empty", "unreadable"})
		for case in cases:
			self.assertEqual(hashlib.sha256(case_image(case)).hexdigest(), case["sha256"], case["id"])

	def test_character_error_rate_counts_substitution_and_deletion(self) -> None:
		self.assertEqual(character_error_rate([("abcd", "abcd")]), 0)
		self.assertEqual(character_error_rate([("abcd", "abxd")]), 0.25)
		self.assertEqual(character_error_rate([("abcd", "")]), 1.0)
		self.assertEqual(character_error_rate([("a  b\n", " a b"), ("cd", "cd")]), 0)


class RealEnginePipelineTests(PipelineCase):
	def test_engine_and_model_versions_are_recorded(self) -> None:
		versions = self.engines.versions
		self.assertTrue(all(versions.values()), versions)
		self.assertEqual(versions["argos_model_manifest"], versions["argos_model_installed"])
		self.assertGreaterEqual(int(versions["tesseract"].split(".")[0]), 5)
		print("engine_versions=" + json.dumps(versions, sort_keys=True), file=sys.stderr)

	def test_images_become_translations_that_meet_the_contract_and_quality(self) -> None:
		server = self.make_server()
		session, websocket = self.open_session(server)
		pairs: dict[str, list[tuple[str, str]]] = {"clear": [], "complex": []}
		frame_id = 0
		for case in load_cases():
			frame_id += 1
			websocket.send(frame_message(session, frame_id, case))
			messages = read_until(websocket, is_result(frame_id))
			result = messages[-1]
			with self.subTest(case=case["id"]):
				states = [m["state"] for m in messages if m["type"] == "state"]
				self.assertEqual(states, ["processing", "ready"])
				self.assertEqual(len({m["correlation_id"] for m in messages if m["type"] != "heartbeat"}), 1)
				self.assertEqual(
					(result["session_id"], result["generation"], result["dictionary_revision"]),
					(session["session_id"], session["generation"], session["dictionary_revision"]),
				)
				self.assertEqual((result["image_width"], result["image_height"]), (case["width"], case["height"]))
				self.assertGreaterEqual(result["server_processing_ms"], 0)
				for region in result["regions"]:
					rect = region["rect"]
					# 低信頼度の誤認識を訳文として返さない(領域下限は単語下限より厳しい)
					self.assertGreaterEqual(region["confidence"], REGION_MIN_CONFIDENCE)
					self.assertTrue(0 <= rect["left"] < rect["right"] <= case["width"])
					self.assertTrue(0 <= rect["top"] < rect["bottom"] <= case["height"])
				if case["group"] == "clear":
					# 前処理の拡大・白縁を元画像座標へ戻せていること(描画位置は生成スクリプトの固定値: 配信矩形は左約25px・上約25px)
					rect = result["regions"][0]["rect"]
					self.assertTrue(22 <= rect["left"] <= 30 and 22 <= rect["top"] <= 28, rect)
				recognized = " ".join(region["source"] for region in result["regions"])
				if case["group"] in pairs:
					pairs[case["group"]].append((case["expected_text"], recognized))
				if case["group"] in ("clear", "complex"):
					self.assertEqual(result["status"], "ok" if result["regions"] else "empty")
				else:
					# 空・読めない画像は成功扱いにせず、領域なしのemptyで返す。
					self.assertEqual((result["status"], result["regions"]), ("empty", []))
				if case["group"] == "clear":
					self.assertEqual(result["status"], "ok")
					for region in result["regions"]:
						self.assertRegex(region["translation"], JAPANESE)
						self.assertNotEqual(region["translation"], region["source"])
		clear = character_error_rate(pairs["clear"])
		complex_ = character_error_rate(pairs["complex"])
		print("ocr_cer=" + json.dumps({"clear": clear, "complex": complex_, "complex_limit_met": complex_ <= COMPLEX_CER_LIMIT,
			"clear_images": len(pairs["clear"]), "complex_images": len(pairs["complex"])}), file=sys.stderr)
		self.assertLessEqual(clear, CLEAR_CER_LIMIT)
		self.assertLessEqual(complex_, COMPLEX_CER_LIMIT)
		# 回帰検出用: 現在の前処理は固定4枚で0%。15%基準だけでは二値化の欠落(9.2%)を見逃すため、
		# 固定画像に対する実測値を下限として固定する。基準の緩和ではなく、悪化を検出するための追加基準。
		self.assertLessEqual(complex_, COMPLEX_REGRESSION_LIMIT)
		websocket.__exit__(None, None, None)
		self.settle(server)

	def test_unknown_or_out_of_frame_positions_are_delivered_without_a_rectangle(self) -> None:
		case = next(item for item in load_cases() if item["id"] == "clear-01")
		for mode in ("unavailable", "outside"):
			with self.subTest(mode=mode):
				server = self.make_server(UnpositionedOcr(self.engines.ocr, mode))
				session, websocket = self.open_session(server)
				websocket.send(frame_message(session, 1, case))
				result = read_until(websocket, is_result(1))[-1]
				self.assertEqual(result["status"], "ok")
				self.assertEqual([region["rect"] for region in result["regions"]], [None])
				self.assertRegex(result["regions"][0]["translation"], JAPANESE)
				websocket.__exit__(None, None, None)
				self.settle(server)

	def test_only_the_latest_waiting_frame_is_translated_under_load(self) -> None:
		recorder = DropRecorder()
		ocr = gated(self.engines)
		server = self.make_server(ocr, observer=recorder)
		session, websocket = self.open_session(server)
		cases = [item for item in load_cases() if item["group"] == "clear"]
		websocket.send(frame_message(session, 1, cases[0]))
		self.assertTrue(ocr.started.wait(120))  # 実OCRを保留し、以降を待機枠に入れる
		for frame_id in (2, 3, 4):
			websocket.send(frame_message(session, frame_id, cases[frame_id - 1]))
		self.assertTrue(recorder.wait_for("replaced_waiting_frame", 2))
		ocr.release.set()
		messages = read_until(websocket, is_result(4))
		results = [message for message in messages if message["type"] == "result"]
		self.assertEqual([message["frame_id"] for message in results], [1, 4])
		self.assertEqual(ocr.calls, 2)  # 置換された2・3枚目は実OCRに渡らない
		self.assertTrue(all(JAPANESE.search(r["regions"][0]["translation"]) for r in results))
		websocket.__exit__(None, None, None)
		self.settle(server)


if __name__ == "__main__":
	unittest.main()
