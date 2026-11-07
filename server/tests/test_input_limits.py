import asyncio
import json
import unittest
from pathlib import Path

from PIL import Image
import yaml

from screen_translation_server.api.input_limits import (
	InputLimitError,
	ROI_MAX_HEIGHT,
	ROI_MAX_PIXELS,
	ROI_MAX_WIDTH,
	parse_binary_message,
	read_limited_body,
	validate_binary_frame_size,
	validate_image_payload,
	validate_json_body_length,
	validate_roi,
)


class InputLimitTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls) -> None:
		candidates = [Path(__file__).resolve().parents[index] / "contracts" for index in (1, 2)]
		cls.contracts = next((path for path in candidates if (path / "fixtures/binary-message-boundaries.json").is_file()), candidates[0])
		if not (cls.contracts / "fixtures/binary-message-boundaries.json").is_file():
			raise unittest.SkipTest("契約fixtureを含むworktreeで実行してください")

	def test_binary_fixture_boundaries_match_the_contract(self) -> None:
		fixture = json.loads((self.contracts / "fixtures/binary-message-boundaries.json").read_text(encoding="utf-8"))
		for case in fixture["cases"]:
			with self.subTest(case=case["name"]):
				try:
					validate_binary_frame_size(
						magic=case["magic"].encode("ascii"),
						metadata_length=case["metadata_bytes"],
						payload_length=case["image_payload_bytes"],
						declared_payload_length=case["declared_payload_bytes"],
						message_length=case["message_bytes"],
					)
					accepted = True
				except InputLimitError:
					accepted = False
				self.assertEqual(accepted, case["accepted"])
				if not case["accepted"]:
					with self.assertRaises(InputLimitError):
						validate_binary_frame_size(
							magic=case["magic"].encode("ascii"),
							metadata_length=case["metadata_bytes"],
							payload_length=case["image_payload_bytes"],
							declared_payload_length=case["declared_payload_bytes"],
							message_length=case["message_bytes"],
						)

	def test_binary_message_rejects_truncation_surplus_and_bad_header(self) -> None:
		image = b"x"
		metadata = json.dumps({
			"contract_version": 1,
			"session_id": "00000000-0000-4000-8000-000000000001",
			"generation": 1,
			"frame_id": 1,
			"dictionary_revision": 1,
			"image_width": 64,
			"image_height": 32,
			"content_type": "image/png",
			"image_length": 1,
		}).encode("utf-8")
		message = b"STF1" + len(metadata).to_bytes(4, "big") + metadata + image
		self.assertEqual(parse_binary_message(message).metadata["image_length"], 1)
		for invalid in (message[:-1], message + b"x", b"STF2" + message[4:], b"STF1\x00\x00\x00\x00"):
			with self.subTest(invalid_length=len(invalid)), self.assertRaises(InputLimitError):
				parse_binary_message(invalid)

	def test_roi_limits_include_each_dimension_and_total_pixels(self) -> None:
		for width, height, expected in (
			(64, 32, True), (1280, 300, True),
			(63, 32, False), (64, 31, False), (1281, 32, False),
			(64, 301, False), (1281, 300, False), (1280, 301, False),
		):
			accepted = True
			try:
				validate_roi(width, height)
			except InputLimitError:
				accepted = False
			with self.subTest(width=width, height=height):
				self.assertEqual(accepted, expected)

	def test_roi_boundary_matches_contract_compatibility_fixtures(self) -> None:
		fixture = json.loads((self.contracts / "fixtures/compatibility.json").read_text(encoding="utf-8"))
		cases = {case["id"]: case for case in fixture["cases"]}
		for name, width, height, expected in (
			("frame-valid-maximum", 1280, 300, True),
			("stream-result-width-too-large", 1281, 300, False),
			("frame-area-too-large", 1280, 301, False),
		):
			case = cases[name]
			self.assertEqual(case["expected"] == "accept", expected)
			value = case["value"]
			self.assertEqual((value["image_width"], value["image_height"]), (width, height))
			with self.subTest(case=name):
				accepted = True
				try:
					validate_roi(width, height)
				except InputLimitError:
					accepted = False
				self.assertEqual(accepted, expected)

	def test_roi_limit_constants_match_openapi_contract(self) -> None:
		openapi = yaml.safe_load((self.contracts / "openapi.yaml").read_text(encoding="utf-8"))
		limits = openapi["paths"]["/api/v1/stream"]["get"]["x-websocket"]["binaryMessage"]
		self.assertEqual((ROI_MAX_WIDTH, ROI_MAX_HEIGHT, ROI_MAX_PIXELS), (
			limits["maximumImageWidth"], limits["maximumImageHeight"], limits["maximumImagePixels"],
		))

	def test_image_size_type_and_real_format_are_checked(self) -> None:
		from io import BytesIO

		buffer = BytesIO()
		Image.new("RGB", (64, 32), "white").save(buffer, format="PNG")
		payload = buffer.getvalue()
		validate_image_payload(payload, "image/png", 64, 32)
		with self.assertRaises(InputLimitError):
			validate_image_payload(payload, "image/jpeg", 64, 32)
		with self.assertRaises(InputLimitError):
			validate_image_payload(payload, "image/png", 65, 32)
		with self.assertRaises(InputLimitError):
			validate_image_payload(b"not an image", "image/png", 64, 32)

	def test_json_body_length_is_bounded_by_declared_and_received_bytes(self) -> None:
		validate_json_body_length(10, 10)
		for declared, received in ((-1, 0), (None, 1_048_577), (11, 10), (9, 10)):
			with self.subTest(declared=declared, received=received), self.assertRaises(InputLimitError):
				validate_json_body_length(declared, received)

	def test_slow_or_oversized_http_body_is_stopped_with_configured_limits(self) -> None:
		async def run_body_test() -> None:
			async def normal_chunks():
				yield b"{"
				yield b"}"

			self.assertEqual(await read_limited_body(normal_chunks(), maximum=2, timeout_seconds=1), b"{}")

			async def oversized_chunks():
				yield b"abc"

			with self.assertRaises(InputLimitError):
				await read_limited_body(oversized_chunks(), maximum=2, timeout_seconds=1)

			async def delayed_chunks():
				yield b"{"
				await asyncio.sleep(0.05)
				yield b"}"

			with self.assertRaises(InputLimitError):
				await read_limited_body(delayed_chunks(), maximum=2, timeout_seconds=0.005)

		asyncio.run(run_body_test())

	def test_authenticated_binary_path_rejects_credentials_before_image_decode(self) -> None:
		from unittest.mock import patch

		from screen_translation_server.api.input_limits import validate_authenticated_binary_message
		from screen_translation_server.security.auth import AuthenticationError, CredentialStore, SecurityPolicy

		with patch("screen_translation_server.api.input_limits.Image.open") as image_open:
			with self.assertRaises(AuthenticationError):
				validate_authenticated_binary_message(
					b"not a frame",
					CredentialStore([]),
					SecurityPolicy(frozenset({"server.example"})),
					"Bearer invalid",
					is_secure=True,
					host="server.example",
					origin=None,
				)
		image_open.assert_not_called()


if __name__ == "__main__":
	unittest.main()
