import json
import unittest
from pathlib import Path

from PIL import Image

from screen_translation_server.api.input_limits import (
	InputLimitError,
	parse_binary_message,
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
		for width, height in ((64, 32), (1920, 1080)):
			validate_roi(width, height)
		for width, height in ((63, 32), (64, 31), (1921, 32), (64, 1081), (1920, 1080)):
			if width * height > 2_073_600 or width > 1920 or height > 1080 or width < 64 or height < 32:
				with self.subTest(width=width, height=height), self.assertRaises(InputLimitError):
					validate_roi(width, height)

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

	def test_authenticated_binary_path_rejects_credentials_before_image_decode(self) -> None:
		from unittest.mock import patch

		from screen_translation_server.api.input_limits import validate_authenticated_binary_message
		from screen_translation_server.security.auth import AuthenticationError, CredentialStore

		with patch("screen_translation_server.api.input_limits.Image.open") as image_open:
			with self.assertRaises(AuthenticationError):
				validate_authenticated_binary_message(b"not a frame", CredentialStore([]), "Bearer invalid")
		image_open.assert_not_called()


if __name__ == "__main__":
	unittest.main()
