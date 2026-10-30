import json
import unittest
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


class ContractFixtureTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls) -> None:
		cls.root = Path(__file__).resolve().parents[2]
		cls.contracts = cls.root / "contracts"
		if not (cls.contracts / "README.md").is_file():
			raise unittest.SkipTest("契約fixtureを含むworktreeで実行してください")
		cls.schemas = {
			path.stem.removesuffix(".schema"): json.loads(path.read_text(encoding="utf-8"))
			for path in (cls.contracts / "schemas").glob("*.schema.json")
		}
		cls.format_checker = FormatChecker()

	@staticmethod
	def read_json(path: Path) -> Any:
		return json.loads(path.read_text(encoding="utf-8"))

	def test_both_clients_and_server_agree_on_every_schema_fixture(self) -> None:
		fixture = self.read_json(self.contracts / "fixtures/compatibility.json")
		self.assertGreaterEqual(len(fixture["cases"]), 30)
		self.assertEqual(len({case["id"] for case in fixture["cases"]}), len(fixture["cases"]))
		for case in fixture["cases"]:
			with self.subTest(case=case["id"]):
				validator = Draft202012Validator(
					self.schemas[case["schema"]], format_checker=self.format_checker
				)
				schema_valid = validator.is_valid(case["value"])
				semantic_valid = self._stream_semantics_valid(case["value"])
				valid = schema_valid and semantic_valid
				if valid:
					self.assertEqual(case["expected"], "accept")
				else:
					self.assertEqual(case["expected"], "reject")
				if not valid:
					self.assertEqual(case["rejection"], "schema" if not schema_valid else "semantic")

	@staticmethod
	def _stream_semantics_valid(value: Any) -> bool:
		if not isinstance(value, dict) or value.get("type") != "result":
			return True
		regions = value.get("regions")
		if not isinstance(regions, list):
			return True
		if (value.get("status") == "empty") != (len(regions) == 0):
			return False
		width = value.get("image_width")
		height = value.get("image_height")
		for region in regions:
			rect = region.get("rect", {})
			if not (0 <= rect.get("left", -1) < rect.get("right", 0) <= width):
				return False
			if not (0 <= rect.get("top", -1) < rect.get("bottom", 0) <= height):
				return False
		return True

	def test_binary_framing_boundaries_have_the_declared_conclusion(self) -> None:
		fixture = self.read_json(self.contracts / "fixtures/binary-message-boundaries.json")
		maximum = fixture["maximum_message_bytes"]
		self.assertGreaterEqual(len(fixture["cases"]), 6)
		for case in fixture["cases"]:
			with self.subTest(case=case["name"]):
				message_bytes = case["header_bytes"] + case["metadata_bytes"] + case["image_payload_bytes"]
				accepted = (
					case["magic"] == "STF1"
					and 1 <= case["metadata_bytes"] <= fixture["components"]["metadata_bytes"]
					and 1 <= case["image_payload_bytes"] <= fixture["components"]["image_payload_bytes"]
					and case["declared_payload_bytes"] == case["image_payload_bytes"]
					and message_bytes <= maximum
					and case["message_bytes"] == message_bytes
				)
				self.assertEqual(accepted, case["accepted"])

	def test_geometry_fixture_is_a_shared_language_independent_contract(self) -> None:
		fixture = self.read_json(self.contracts / "fixtures/geometry/coordinate-cases.json")
		self.assertGreaterEqual(len(fixture["conversions"]), 9)
		self.assertGreaterEqual(len(fixture["roi_cases"]), 5)
		self.assertEqual(
			len({case["id"] for case in fixture["conversions"] + fixture["roi_cases"]}),
			len(fixture["conversions"]) + len(fixture["roi_cases"]),
		)

	def test_session_state_fixture_has_valid_and_invalid_transitions(self) -> None:
		fixture = self.read_json(self.contracts / "fixtures/session-state-cases.json")
		self.assertGreaterEqual(len(fixture["cases"]), 8)
		self.assertEqual({case["expected"] for case in fixture["cases"]}, {"accept", "reject"})
		transitions = {
			(case["from"], case["action"], case["to"])
			for case in fixture["transitions"]
		}
		for case in fixture["cases"]:
			with self.subTest(case=case["id"]):
				self.assertIn(case["from"], fixture["states"])
				self.assertIn(case["to"], fixture["states"])
				self.assertIsInstance(case["action"], str)
				self.assertEqual(
					(case["from"], case["action"], case["to"]) in transitions,
					case["expected"] == "accept",
				)
		for case in fixture["result_cases"]:
			with self.subTest(case=case["id"]):
				self.assertEqual(self._result_rejection(case["result"]), case.get("rejection", "accept"))
				self.assertEqual(self._result_rejection(case["result"]) == "accept", case["expected"] == "accept")

	@staticmethod
	def _result_rejection(value: dict[str, Any]) -> str:
		if value["state"] != "Streaming":
			return "lifecycle"
		if value["session_id"] != value["result_session_id"]:
			return "session"
		if value["generation"] != value["result_generation"]:
			return "generation"
		if not value["last_applied_frame_id"] < value["result_frame_id"] <= value["latest_sent_frame_id"]:
			return "frame_order"
		if value["dictionary_revision"] != value["result_dictionary_revision"]:
			return "revision"
		age = value["now_monotonic_ns"] - value["captured_monotonic_ns"]
		if not 0 <= age <= 5_000_000_000:
			return "expiry"
		return "accept"

	def test_existing_api_error_fixture_catalog_remains_schema_valid(self) -> None:
		validator = Draft202012Validator(self.schemas["error"], format_checker=self.format_checker)
		for fixture in self.read_json(self.contracts / "fixtures/errors.json"):
			with self.subTest(status=fixture["status"], code=fixture["body"]["code"]):
				validator.validate(fixture["body"])
				self.assertIn(fixture["status"], (400, 401, 403, 404, 409, 413, 422, 500, 503))

	def test_every_existing_schema_fixture_is_valid_under_its_draft_2020_12_schema(self) -> None:
		for fixture in self.read_json(self.contracts / "fixtures/control-data.json"):
			with self.subTest(file="control-data", schema=fixture["schema"]):
				Draft202012Validator(
					self.schemas[fixture["schema"]], format_checker=self.format_checker
				).validate(fixture["value"])
		for filename, schema_name in (("frame-metadata.json", "frame-metadata"), ("stream-text.json", "stream-message")):
			validator = Draft202012Validator(self.schemas[schema_name], format_checker=self.format_checker)
			for fixture in self.read_json(self.contracts / "fixtures" / filename):
				with self.subTest(file=filename, case=fixture.get("type", fixture.get("frame_id"))):
					validator.validate(fixture)

	def test_coordinate_conversion_examples_match_contract_values(self) -> None:
		fixture = self.read_json(self.contracts / "fixtures/geometry/coordinate-cases.json")
		for case in fixture["conversions"]:
			with self.subTest(case=case["id"]):
				x, y = case["input_point"]
				operation = case["operation"]
				if operation == "physical_to_image":
					left, top, right, bottom = case["roi"]
					self.assertTrue(left <= x < right and top <= y < bottom)
					actual = [x - left, y - top]
				else:
					origin_x, origin_y = case["monitor_origin_physical"]
					scale = case["dpi"] / 96
					if operation == "physical_to_logical":
						actual = [self._round_pixel((x - origin_x) / scale), self._round_pixel((y - origin_y) / scale)]
					else:
						actual = [origin_x + self._round_pixel(x * scale), origin_y + self._round_pixel(y * scale)]
				self.assertEqual(actual, case["expected_point"])
		for case in fixture["roi_cases"]:
			left, top, right, bottom = case["roi"]
			monitor_left, monitor_top, monitor_right, monitor_bottom = case["monitor"]
			contained = monitor_left <= left < right <= monitor_right and monitor_top <= top < bottom <= monitor_bottom
			self.assertEqual(contained, case["allowed"], case["id"])

	@staticmethod
	def _round_pixel(value: float) -> int:
		return int(value + 0.5) if value >= 0 else int(value - 0.5)


if __name__ == "__main__":
	unittest.main()
