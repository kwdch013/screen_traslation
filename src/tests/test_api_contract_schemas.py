import json
import re
import unittest
from pathlib import Path
from typing import Any


class ApiContractSchemaTests(unittest.TestCase):
	def setUp(self) -> None:
		self.root = Path(__file__).resolve().parents[2]
		self.contracts = self.root / "contracts"
		if not (self.contracts / "README.md").is_file():
			self.skipTest("契約文書を含むリポジトリをマウントして実行してください")
		from jsonschema import Draft202012Validator, FormatChecker, ValidationError
		from referencing import Registry, Resource

		self.Draft202012Validator = Draft202012Validator
		self.ValidationError = ValidationError
		self.format_checker = FormatChecker()
		self.schemas = {
			path.stem.removesuffix(".schema"): self.read_json(path)
			for path in sorted((self.contracts / "schemas").glob("*.schema.json"))
		}
		registry = Registry()
		for path in sorted((self.contracts / "schemas").glob("*.schema.json")):
			schema = self.read_json(path)
			resource = Resource.from_contents(schema)
			registry = registry.with_resource(schema["$id"], resource)
			registry = registry.with_resource(path.as_uri(), resource)
		self.registry = registry

	def read_json(self, path: Path) -> Any:
		return json.loads(path.read_text(encoding="utf-8"))

	def validator(self, schema_name: str):
		return self.Draft202012Validator(
			self.schemas[schema_name], registry=self.registry, format_checker=self.format_checker
		)

	def test_json_schema_documents_are_valid_draft_2020_12(self) -> None:
		self.assertGreaterEqual(len(self.schemas), 8)
		for name, schema in self.schemas.items():
			with self.subTest(schema=name):
				self.Draft202012Validator.check_schema(schema)

	def test_error_fixtures_match_error_schema_and_have_http_status(self) -> None:
		validator = self.validator("error")
		fixtures = self.read_json(self.contracts / "fixtures/errors.json")
		self.assertGreaterEqual(len(fixtures), 6)
		for fixture in fixtures:
			with self.subTest(code=fixture["body"].get("code")):
				self.assertIn(fixture["status"], (400, 401, 403, 404, 409, 413, 422, 500, 503))
				validator.validate(fixture["body"])

	def test_session_and_configuration_fixtures_match_their_schemas(self) -> None:
		fixtures = self.read_json(self.contracts / "fixtures/control-data.json")
		for fixture in fixtures:
			with self.subTest(schema=fixture["schema"]):
				self.validator(fixture["schema"]).validate(fixture["value"])

	def test_websocket_text_fixtures_match_state_and_result_schemas(self) -> None:
		fixtures = self.read_json(self.contracts / "fixtures/stream-text.json")
		for fixture in fixtures:
			with self.subTest(type=fixture.get("type")):
				self.validator("stream-message").validate(fixture)

	def test_frame_metadata_fixtures_enforce_shared_session_and_image_contract(self) -> None:
		fixtures = self.read_json(self.contracts / "fixtures/frame-metadata.json")
		validator = self.validator("frame-metadata")
		self.assertGreaterEqual(len(fixtures), 3)
		for fixture in fixtures:
			with self.subTest(frame_id=fixture.get("frame_id")):
				validator.validate(fixture)
		invalid = dict(fixtures[0], image_width=1921)
		with self.assertRaises(self.ValidationError):
			validator.validate(invalid)
		invalid = dict(fixtures[0], unexpected=True)
		with self.assertRaises(self.ValidationError):
			validator.validate(invalid)
		self.assertIn("session_id", fixtures[0])
		self.assertIn("generation", fixtures[0])
		self.assertIn("frame_id", fixtures[0])
		self.assertIn("dictionary_revision", fixtures[0])

	def test_invalid_uuid_format_is_rejected_by_the_format_checker(self) -> None:
		fixtures = self.read_json(self.contracts / "fixtures/frame-metadata.json")
		invalid = dict(fixtures[0], session_id="not-a-uuid")
		with self.assertRaises(self.ValidationError):
			self.validator("frame-metadata").validate(invalid)

	def test_local_schema_reference_resolves_through_the_registry(self) -> None:
		fixtures = self.read_json(self.contracts / "fixtures/frame-metadata.json")
		wrapper = {
			"$schema": "https://json-schema.org/draft/2020-12/schema",
			"$id": (self.contracts / "schemas/reference-test.schema.json").as_uri(),
			"$ref": "frame-metadata.schema.json",
		}
		validator = self.Draft202012Validator(
			wrapper, registry=self.registry, format_checker=self.format_checker
		)
		validator.validate(fixtures[0])

	def test_binary_message_boundary_fixtures_use_the_framing_total(self) -> None:
		fixture = self.read_json(self.contracts / "fixtures/binary-message-boundaries.json")
		self.assertEqual(fixture["components"], {"header_bytes": 8, "metadata_bytes": 4096, "image_payload_bytes": 4194304})
		self.assertEqual(fixture["maximum_message_bytes"], 4198408)
		openapi = (self.contracts / "openapi.yaml").read_text(encoding="utf-8")
		readme = (self.contracts / "README.md").read_text(encoding="utf-8")
		api_design = (self.root / "docs/v1.0/design/api.md").read_text(encoding="utf-8")
		self.assertIn("maximumMessageBytes: 4198408", openapi)
		self.assertIn("4,198,408 bytes", readme)
		self.assertIn("4,198,408 bytes", api_design)
		for case in fixture["cases"]:
			with self.subTest(case=case["name"]):
				message_bytes = case["header_bytes"] + case["metadata_bytes"] + case["image_payload_bytes"]
				self.assertEqual(message_bytes, case["message_bytes"])
				self.assertEqual(message_bytes <= fixture["maximum_message_bytes"], case["accepted"])
		self.assertEqual(fixture["cases"][0]["message_bytes"], fixture["maximum_message_bytes"])
		self.assertEqual(fixture["cases"][1]["message_bytes"], fixture["maximum_message_bytes"] + 1)

	def test_openapi_and_api_design_link_the_issue_63_contracts_without_copying_them(self) -> None:
		openapi = (self.contracts / "openapi.yaml").read_text(encoding="utf-8")
		api_design = (self.root / "docs/v1.0/design/api.md").read_text(encoding="utf-8")
		for path in ("/api/v1/health", "/api/v1/ready", "/api/v1/sessions", "/api/v1/settings", "/api/v1/glossary", "/api/v1/stream"):
			with self.subTest(path=path):
				self.assertIn(path, openapi)
		self.assertIn("coordinates.md", api_design)
		self.assertIn("session-state.md", api_design)
		self.assertIn("#63", api_design)
		self.assertIn("4 MiB", api_design)
		self.assertIn("2,073,600", api_design)
		coordinates = (self.contracts / "coordinates.md").read_text(encoding="utf-8")
		session_state = (self.contracts / "session-state.md").read_text(encoding="utf-8")
		for field in ("session_id", "generation", "frame_id", "dictionary_revision"):
			with self.subTest(field=field):
				self.assertIn(field, session_state)
		self.assertIn("半開区間", coordinates)
		self.assertIn("physical px", coordinates)

	def test_api_and_contract_readme_relative_links_resolve(self) -> None:
		for document_path in (self.contracts / "README.md", self.root / "docs/v1.0/design/api.md"):
			document = document_path.read_text(encoding="utf-8")
			for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", document):
				if "://" in target or target.startswith("#"):
					continue
				with self.subTest(document=document_path.name, target=target):
					resolved = document_path.parent.joinpath(target.split("#")[0])
					self.assertTrue(resolved.is_file() or resolved.is_dir())


if __name__ == "__main__":
	unittest.main()
