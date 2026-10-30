"""HTTP/WSS入力の長さ・画像形式・ROI境界検証。"""

from __future__ import annotations

import json
import uuid
import warnings
from dataclasses import dataclass
from io import BytesIO
from typing import Any

from PIL import Image, UnidentifiedImageError

from screen_translation_server.security.auth import CredentialStore, Role


HTTP_JSON_MAX_BYTES = 1_048_576
IMAGE_MAX_BYTES = 4_194_304
METADATA_MAX_BYTES = 4_096
BINARY_HEADER_BYTES = 8
BINARY_MESSAGE_MAX_BYTES = 4_198_408
ROI_MIN_WIDTH = 64
ROI_MIN_HEIGHT = 32
ROI_MAX_WIDTH = 1_920
ROI_MAX_HEIGHT = 1_080
ROI_MAX_PIXELS = 2_073_600
_FRAME_FIELDS = frozenset({
	"contract_version", "session_id", "generation", "frame_id", "dictionary_revision",
	"image_width", "image_height", "content_type", "image_length",
})


class InputLimitError(ValueError):
	"""入力拒否。呼出側は契約の安全なエラーへ変換する。"""


@dataclass(frozen=True, slots=True)
class BinaryMessage:
	metadata: dict[str, Any]
	image: bytes


def validate_binary_frame_size(
	*,
	magic: bytes,
	metadata_length: int,
	payload_length: int,
	declared_payload_length: int,
	message_length: int,
) -> None:
	if magic != b"STF1":
		raise InputLimitError("binary headerが不正です。")
	if not 1 <= metadata_length <= METADATA_MAX_BYTES:
		raise InputLimitError("metadata長が上限外です。")
	if not 1 <= payload_length <= IMAGE_MAX_BYTES or declared_payload_length != payload_length:
		raise InputLimitError("image長が上限外です。")
	expected_length = BINARY_HEADER_BYTES + metadata_length + payload_length
	if message_length != expected_length or message_length > BINARY_MESSAGE_MAX_BYTES:
		raise InputLimitError("binary message長が不正です。")


def parse_binary_message(message: bytes) -> BinaryMessage:
	if len(message) < BINARY_HEADER_BYTES or len(message) > BINARY_MESSAGE_MAX_BYTES:
		raise InputLimitError("binary message長が不正です。")
	if message[:4] != b"STF1":
		raise InputLimitError("binary headerが不正です。")
	metadata_length = int.from_bytes(message[4:8], "big")
	if not 1 <= metadata_length <= METADATA_MAX_BYTES or BINARY_HEADER_BYTES + metadata_length > len(message):
		raise InputLimitError("metadata長が不正です。")
	metadata_bytes = message[BINARY_HEADER_BYTES:BINARY_HEADER_BYTES + metadata_length]
	try:
		metadata = json.loads(metadata_bytes.decode("utf-8"), object_pairs_hook=_unique_object)
	except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
		raise InputLimitError("metadata形式が不正です。") from None
	if not isinstance(metadata, dict) or set(metadata) != _FRAME_FIELDS:
		raise InputLimitError("metadata項目が不正です。")
	_validate_frame_metadata(metadata)
	image = message[BINARY_HEADER_BYTES + metadata_length:]
	image_length = metadata.get("image_length")
	if isinstance(image_length, bool) or not isinstance(image_length, int):
		raise InputLimitError("image長が不正です。")
	validate_binary_frame_size(
		magic=message[:4],
		metadata_length=metadata_length,
		payload_length=len(image),
		declared_payload_length=image_length,
		message_length=len(message),
	)
	validate_roi(metadata.get("image_width"), metadata.get("image_height"))
	return BinaryMessage(metadata, image)


def validate_authenticated_binary_message(
	message: bytes,
	credentials: CredentialStore,
	authorization: str | None,
	*,
	allowed_roles: set[Role] | frozenset[Role] = frozenset({Role.DEVICE}),
) -> BinaryMessage:
	"""資格情報を先に検証し、受信長・metadata・実画像を確認してから返す。"""
	credentials.authenticate(authorization, allowed_roles)
	frame = parse_binary_message(message)
	validate_image_payload(
		frame.image,
		frame.metadata["content_type"],
		frame.metadata["image_width"],
		frame.metadata["image_height"],
	)
	return frame


def validate_json_body_length(declared_length: object, received_length: int, maximum: int = HTTP_JSON_MAX_BYTES) -> None:
	if isinstance(received_length, bool) or not isinstance(received_length, int):
		raise InputLimitError("要求本文長が不正です。")
	if received_length < 0 or received_length > maximum:
		raise InputLimitError("要求本文が上限を超えています。")
	if declared_length is not None and (
		isinstance(declared_length, bool)
		or not isinstance(declared_length, int)
		or declared_length < 0
		or declared_length != received_length
		or declared_length > maximum
	):
		raise InputLimitError("要求本文長が不正です。")


def validate_roi(width: object, height: object) -> None:
	if isinstance(width, bool) or isinstance(height, bool) or not isinstance(width, int) or not isinstance(height, int):
		raise InputLimitError("ROI寸法が不正です。")
	if not ROI_MIN_WIDTH <= width <= ROI_MAX_WIDTH or not ROI_MIN_HEIGHT <= height <= ROI_MAX_HEIGHT:
		raise InputLimitError("ROI寸法が上限外です。")
	if width * height > ROI_MAX_PIXELS:
		raise InputLimitError("ROI画素数が上限を超えています。")


def validate_image_payload(payload: bytes, content_type: object, width: object, height: object) -> None:
	validate_roi(width, height)
	if not isinstance(payload, bytes) or not 1 <= len(payload) <= IMAGE_MAX_BYTES:
		raise InputLimitError("image payload長が上限外です。")
	expected_format = {"image/png": "PNG", "image/jpeg": "JPEG"}.get(content_type) if isinstance(content_type, str) else None
	if expected_format is None:
		raise InputLimitError("image形式が不正です。")
	try:
		with warnings.catch_warnings():
			warnings.simplefilter("error", Image.DecompressionBombWarning)
			with Image.open(BytesIO(payload)) as image:
				if image.format != expected_format or image.size != (width, height):
					raise InputLimitError("image形式または寸法が一致しません。")
				image.verify()
			with Image.open(BytesIO(payload)) as image:
				image.load()
	except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
		raise InputLimitError("imageを検証できません。") from None


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
	result: dict[str, Any] = {}
	for key, value in pairs:
		if key in result:
			raise ValueError("重複key")
		result[key] = value
	return result


def _validate_frame_metadata(metadata: dict[str, Any]) -> None:
	version = metadata["contract_version"]
	if isinstance(version, bool) or version != 1:
		raise InputLimitError("metadata versionが不正です。")
	session_id = metadata["session_id"]
	if not isinstance(session_id, str):
		raise InputLimitError("session idが不正です。")
	try:
		uuid.UUID(session_id)
	except ValueError:
		raise InputLimitError("session idが不正です。") from None
	for name in ("generation", "frame_id", "dictionary_revision", "image_length"):
		value = metadata[name]
		if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 18_446_744_073_709_551_615:
			raise InputLimitError("metadata integerが不正です。")
	if metadata["content_type"] not in ("image/png", "image/jpeg"):
		raise InputLimitError("image形式が不正です。")
