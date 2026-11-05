import json
import re
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


class StreamErrorHandlingFixtureTests(unittest.TestCase):
	"""WSS errorのcodeごとの扱い(致命/非致命・再試行)の契約fixtureを、schemaとサーバー実装に突き合わせる (Issue #226)。"""

	@classmethod
	def setUpClass(cls) -> None:
		cls.root = Path(__file__).resolve().parents[2]
		cls.contracts = cls.root / "contracts"
		if not (cls.contracts / "README.md").is_file():
			raise unittest.SkipTest("契約fixtureを含むworktreeで実行してください")
		cls.fixture = json.loads((cls.contracts / "fixtures/stream-error-handling.json").read_text(encoding="utf-8"))
		cls.schema = json.loads((cls.contracts / "schemas/stream-message.schema.json").read_text(encoding="utf-8"))
		error_branch = next(item for item in cls.schema["oneOf"] if item["properties"]["type"].get("const") == "error")
		cls.enum_codes = set(error_branch["properties"]["code"]["enum"])
		cls.source = "\n".join(
			path.read_text(encoding="utf-8")
			for path in (cls.root / "server/src/screen_translation_server").rglob("*.py")
		) if (cls.root / "server/src/screen_translation_server").is_dir() else ""

	def test_every_schema_code_has_exactly_one_disposition(self) -> None:
		codes = [item["code"] for item in self.fixture["codes"]]
		self.assertEqual(len(codes), len(set(codes)))
		self.assertEqual(set(codes), self.enum_codes)

	def test_dispositions_and_retry_values_are_declared(self) -> None:
		for item in self.fixture["codes"]:
			with self.subTest(code=item["code"]):
				self.assertIn(item["disposition"], {"fatal", "non_fatal"})
				self.assertIn(item["retry"], self.fixture["retry"])
				# 致命は再試行しない(閉じる)。非致命は閉じずに次のframeを処理する
				self.assertEqual(item["retry"], "none" if item["disposition"] == "fatal" else "next_frame")

	def test_unknown_codes_are_fatal(self) -> None:
		self.assertEqual(self.fixture["unknown_code"]["disposition"], "fatal")
		validator = Draft202012Validator(self.schema, format_checker=FormatChecker())
		unknown = {
			"type": "error", "code": "SOMETHING_NEW", "correlation_id": "00000000-0000-4000-8000-000000000020",
			"session_id": "11111111-1111-4111-8111-111111111111", "generation": 1, "frame_id": 1, "dictionary_revision": 1,
		}
		self.assertFalse(validator.is_valid(unknown))

	def test_every_code_is_a_valid_error_message(self) -> None:
		validator = Draft202012Validator(self.schema, format_checker=FormatChecker())
		for item in self.fixture["codes"]:
			with self.subTest(code=item["code"]):
				self.assertTrue(validator.is_valid({
					"type": "error", "code": item["code"], "correlation_id": "00000000-0000-4000-8000-000000000020",
					"session_id": "11111111-1111-4111-8111-111111111111", "generation": 1, "frame_id": 1, "dictionary_revision": 1,
				}))

	def test_server_sends_non_fatal_codes_as_messages_and_never_sends_fatal_ones(self) -> None:
		if not self.source:
			self.skipTest("サーバーのソースが無い環境では実装との突き合わせを行わない")
		for item in self.fixture["codes"]:
			code = item["code"]
			with self.subTest(code=code):
				if item["server_sends_as_error_message"]:
					self.assertIn(f'"{code}"', self.source, f"{code} をerror messageとして送る実装が見つかりません")
					self.assertEqual(item["disposition"], "non_fatal", "error messageとして送るcodeはstreamを閉じない設計")
				else:
					self.assertIsNone(
						re.search(rf'(publish_error|error_message)\(\s*"{code}"', self.source),
						f"{code} はerror messageとして送らない契約",
					)


if __name__ == "__main__":
	unittest.main()
