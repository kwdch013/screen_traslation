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

	def read_json(self, path: Path) -> Any:
		return json.loads(path.read_text(encoding="utf-8"))

	def validate(self, value: Any, schema: dict[str, Any], root: Path) -> list[str]:
		if "$ref" in schema:
			path, _, fragment = schema["$ref"].partition("#")
			ref = self.read_json(root / path)
			for part in fragment.removeprefix("/").split("/"):
				if part:
					ref = ref[part]
			return self.validate(value, ref, root)

		errors: list[str] = []
		if "oneOf" in schema:
			matches = sum(not self.validate(value, option, root) for option in schema["oneOf"])
			if matches != 1:
				errors.append("oneOf")
		if "const" in schema and value != schema["const"]:
			errors.append("const")
		if "enum" in schema and value not in schema["enum"]:
			errors.append("enum")
		types = schema.get("type")
		if types is not None:
			types = [types] if isinstance(types, str) else types
			checks = {
				"object": lambda item: isinstance(item, dict),
				"array": lambda item: isinstance(item, list),
				"string": lambda item: isinstance(item, str),
				"integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
				"number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
				"boolean": lambda item: isinstance(item, bool),
				"null": lambda item: item is None,
			}
			if not any(checks[kind](value) for kind in types):
				return ["type"]
		if isinstance(value, dict):
			for key in schema.get("required", []):
				if key not in value:
					errors.append(f"required:{key}")
			properties = schema.get("properties", {})
			for key, item in value.items():
				if key in properties:
					errors.extend(f"{key}.{error}" for error in self.validate(item, properties[key], root))
				elif schema.get("additionalProperties") is False:
					errors.append(f"additional:{key}")
		elif isinstance(value, list):
			if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", float("inf")):
				errors.append("items-length")
			if "items" in schema:
				for index, item in enumerate(value):
					errors.extend(f"[{index}].{error}" for error in self.validate(item, schema["items"], root))
		elif isinstance(value, str):
			if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", float("inf")):
				errors.append("string-length")
			if "pattern" in schema and re.fullmatch(schema["pattern"], value) is None:
				errors.append("pattern")
		elif isinstance(value, (int, float)) and not isinstance(value, bool):
			if value < schema.get("minimum", float("-inf")) or value > schema.get("maximum", float("inf")):
				errors.append("range")
		return errors

	def test_json_schema_documents_are_valid_draft_2020_12(self) -> None:
		paths = sorted((self.contracts / "schemas").glob("*.schema.json"))
		self.assertGreaterEqual(len(paths), 8)
		for path in paths:
			with self.subTest(schema=path.name):
				schema = self.read_json(path)
				self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
				self.assertIsInstance(schema.get("$id"), str)
				self.assertTrue("type" in schema or "oneOf" in schema)

	def test_error_fixtures_match_error_schema_and_have_http_status(self) -> None:
		schema = self.read_json(self.contracts / "schemas/error.schema.json")
		fixtures = self.read_json(self.contracts / "fixtures/errors.json")
		self.assertGreaterEqual(len(fixtures), 6)
		for fixture in fixtures:
			with self.subTest(code=fixture["body"].get("code")):
				self.assertIn(fixture["status"], (400, 401, 403, 404, 409, 413, 422, 500, 503))
				self.assertEqual(self.validate(fixture["body"], schema, self.contracts), [])

	def test_session_and_configuration_fixtures_match_their_schemas(self) -> None:
		fixtures = self.read_json(self.contracts / "fixtures/control-data.json")
		for fixture in fixtures:
			with self.subTest(schema=fixture["schema"]):
				schema = self.read_json(self.contracts / "schemas" / f"{fixture['schema']}.schema.json")
				self.assertEqual(self.validate(fixture["value"], schema, self.contracts), [])

	def test_websocket_text_fixtures_match_state_and_result_schemas(self) -> None:
		fixtures = self.read_json(self.contracts / "fixtures/stream-text.json")
		for fixture in fixtures:
			with self.subTest(type=fixture.get("type")):
				schema = self.read_json(self.contracts / "schemas/stream-message.schema.json")
				self.assertEqual(self.validate(fixture, schema, self.contracts), [])

	def test_frame_metadata_fixtures_enforce_shared_session_and_image_contract(self) -> None:
		fixtures = self.read_json(self.contracts / "fixtures/frame-metadata.json")
		schema = self.read_json(self.contracts / "schemas/frame-metadata.schema.json")
		self.assertGreaterEqual(len(fixtures), 3)
		for fixture in fixtures:
			with self.subTest(frame_id=fixture.get("frame_id")):
				self.assertEqual(self.validate(fixture, schema, self.contracts), [])
		invalid = dict(fixtures[0], image_width=1921)
		self.assertTrue(self.validate(invalid, schema, self.contracts))
		invalid = dict(fixtures[0], unexpected=True)
		self.assertTrue(self.validate(invalid, schema, self.contracts))
		self.assertIn("session_id", fixtures[0])
		self.assertIn("generation", fixtures[0])
		self.assertIn("frame_id", fixtures[0])
		self.assertIn("dictionary_revision", fixtures[0])

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
