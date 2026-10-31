"""設定・辞書APIテストで共有するapp構築と契約検証の補助。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import hashlib
from io import BytesIO
import json
from pathlib import Path
import struct
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from PIL import Image

from screen_translation_server.app import create_app
from screen_translation_server.security.auth import Credential, CredentialStore, Role, SecurityPolicy
from screen_translation_server.sessions import SessionManager
from screen_translation_server.storage import GlossaryStore, SettingsStore

DEVICE_TOKEN = "d" * 64
ADMIN_TOKEN = "a" * 64
DEVICE = {"Authorization": f"Bearer {DEVICE_TOKEN}"}
ADMIN = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
BASE_URL = "https://server.example"


def _contracts_root() -> Path:
	return next(
		parent / "contracts" for parent in Path(__file__).resolve().parents
		if (parent / "contracts/schemas/error.schema.json").is_file()
	)


def load_json(relative: str) -> Any:
	return json.loads((_contracts_root() / relative).read_text(encoding="utf-8"))


def validate_schema(name: str, value: object) -> None:
	schema = load_json(f"schemas/{name}.schema.json")
	Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)


def error_fixture(status: int, code: str) -> dict[str, Any]:
	for item in load_json("fixtures/errors.json"):
		if item["status"] == status and item["body"]["code"] == code:
			return item["body"]
	raise AssertionError("fixtureがありません。")


def assert_error_matches_fixture(case: Any, response: Any, status: int, code: str) -> None:
	"""本文が契約schemaに合い、correlation_id以外がfixtureと一致する。"""
	case.assertEqual(response.status_code, status)
	body = response.json()
	validate_schema("error", body)
	expected = error_fixture(status, code)
	case.assertEqual({k: v for k, v in body.items() if k != "correlation_id"},
		{k: v for k, v in expected.items() if k != "correlation_id"})


def credential(token: str, role: Role) -> Credential:
	salt = hashlib.sha256(role.value.encode()).digest()[:16]
	return Credential(role.value, salt, hashlib.sha256(salt + token.encode("ascii")).digest(),
		role, datetime.now(UTC) + timedelta(days=1))


def make_app(data_dir: Path | None, **options: Any):
	"""固定の資格情報で、保存先を注入したappを作る。"""
	if data_dir is not None:
		options.setdefault("settings_store", SettingsStore(data_dir))
		options.setdefault("glossary_store", GlossaryStore(data_dir))
	options.setdefault("sessions", SessionManager(clock=lambda: 1.0, sleep=asyncio.sleep))
	return create_app(
		credentials=CredentialStore([credential(DEVICE_TOKEN, Role.DEVICE), credential(ADMIN_TOKEN, Role.ADMIN)]),
		policy=SecurityPolicy(frozenset({"server.example"})),
		is_ready=True,
		**options,
	)


def binary_frame(session: dict[str, Any], frame_id: int, revision: int) -> bytes:
	image_buffer = BytesIO()
	Image.new("RGB", (64, 32)).save(image_buffer, format="PNG")
	image = image_buffer.getvalue()
	metadata = json.dumps({
		"contract_version": 1, "session_id": session["session_id"],
		"generation": session["generation"], "frame_id": frame_id,
		"dictionary_revision": revision,
		"image_width": 64, "image_height": 32, "content_type": "image/png",
		"image_length": len(image),
	}, separators=(",", ":")).encode("utf-8")
	return b"STF1" + struct.pack(">I", len(metadata)) + metadata + image
