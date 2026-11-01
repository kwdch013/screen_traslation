"""本番Compose・Dockerfile・環境雛形の静的検証。資源上限・非root・healthcheck・秘密非埋め込みを固定する。"""

from __future__ import annotations

import json
import re
import unittest
from typing import Any

from production_config import (
	COMPOSE_PATH, DOCKERFILE_PATH, ENV_EXAMPLE_PATH, MANIFEST_PATH,
	environment_of, load_compose, normalize_ports, normalize_volumes, read_env_example, to_bytes,
)
from screen_translation_server.engines.lifecycle import ModelManifest

GIB = 1024**3
SECRET_NAME = re.compile(r"TOKEN|SECRET|PASSWORD|PRIVATE_KEY|API_KEY", re.IGNORECASE)
# 実行する3サービス(常駐server・モデル導入・管理CLI)は同じ強化設定を守る。
SERVICES = ("server", "prepare-model", "admin")


class ComposeTest(unittest.TestCase):
	@classmethod
	def setUpClass(cls) -> None:
		cls.compose: dict[str, Any] = load_compose()
		cls.services: dict[str, Any] = cls.compose["services"]

	def test_all_services_stay_within_cpu_and_memory_limits(self) -> None:
		for name in SERVICES:
			with self.subTest(name):
				service = self.services[name]
				self.assertEqual(float(service["cpus"]), 2.0)
				self.assertEqual(to_bytes(service["mem_limit"]), 4 * GIB)
				# swapで4 GiBを超えさせない。
				self.assertEqual(to_bytes(service["memswap_limit"]), 4 * GIB)
				self.assertGreater(int(service["pids_limit"]), 0)

	def test_ocr_and_torch_threads_follow_the_cpu_limit(self) -> None:
		environment = environment_of(self.services["server"])
		self.assertEqual(environment["OMP_THREAD_LIMIT"], "1")
		self.assertLessEqual(int(environment["OMP_NUM_THREADS"] or "0"), 2)

	def test_read_only_root_fs_has_writable_config_dir_for_argos(self) -> None:
		# Argosはimport時にXDG_CONFIG_HOME(未設定ならHOME)配下へディレクトリを作る。非root・read_onlyでは失敗する。
		for name in ("server", "prepare-model"):
			environment = environment_of(self.services[name])
			self.assertTrue(environment["XDG_CONFIG_HOME"].startswith("/tmp/"), name)
			self.assertTrue(environment["XDG_DATA_HOME"].startswith("/models/"), name)

	def test_all_services_run_as_non_root_with_hardening(self) -> None:
		for name in SERVICES:
			with self.subTest(name):
				service = self.services[name]
				uid, _, gid = str(service["user"]).partition(":")
				self.assertTrue(uid.isdigit() and gid.isdigit(), service["user"])
				self.assertGreater(int(uid), 0)
				self.assertGreater(int(gid), 0)
				self.assertTrue(service["read_only"])
				self.assertEqual(service["cap_drop"], ["ALL"])
				self.assertIn("no-new-privileges:true", service["security_opt"])
				self.assertTrue(service["init"])
				self.assertNotIn("privileged", service)

	def test_server_restarts_and_logs_are_rotated(self) -> None:
		self.assertEqual(self.services["server"]["restart"], "unless-stopped")
		for name in SERVICES:
			with self.subTest(name):
				logging = self.services[name]["logging"]
				self.assertEqual(logging["driver"], "json-file")
				self.assertRegex(str(logging["options"]["max-size"]), r"^\d+[kmg]$")
				self.assertGreaterEqual(int(logging["options"]["max-file"]), 2)

	def test_server_healthcheck_uses_the_in_image_probe(self) -> None:
		check = self.services["server"]["healthcheck"]
		self.assertEqual(check["test"][:2], ["CMD", "python"])
		self.assertIn("screen_translation_server.healthcheck", check["test"])
		for key in ("interval", "timeout", "retries", "start_period"):
			self.assertIn(key, check)

	def test_port_uses_env_variable_and_defaults_to_loopback(self) -> None:
		(address, published, target), = normalize_ports(self.services["server"]["ports"])
		self.assertEqual(address, "127.0.0.1")
		self.assertEqual(target, 8443)
		self.assertGreater(published, 1023)
		self.assertNotIn("ports", self.services["prepare-model"])
		self.assertNotIn("ports", self.services["admin"])

	def test_raw_port_definition_follows_the_compose_port_convention(self) -> None:
		text = COMPOSE_PATH.read_text(encoding="utf-8")
		self.assertIn('"${SERVER_BIND_ADDRESS:-127.0.0.1}:${SERVER_API_PORT:-8443}:8443"', text)
		env = read_env_example()
		self.assertIn("SERVER_API_PORT", env)
		self.assertIn("SERVER_BIND_ADDRESS", env)
		self.assertEqual(env["SERVER_BIND_ADDRESS"], "127.0.0.1")

	def test_required_settings_fail_closed_when_unset(self) -> None:
		text = COMPOSE_PATH.read_text(encoding="utf-8")
		self.assertIn("${SERVER_ALLOWED_HOSTS:?", text)
		self.assertIn("${SERVER_TLS_DIR:?", text)
		env = read_env_example()
		self.assertEqual(env["SERVER_ALLOWED_HOSTS"], "")
		self.assertEqual(env["SERVER_TLS_DIR"], "")

	def test_state_lives_in_separate_named_volumes(self) -> None:
		volumes = {item["target"]: item for item in normalize_volumes(self.services["server"]["volumes"])}
		for target in ("/data", "/credentials", "/models"):
			self.assertEqual(volumes[target]["type"], "volume", target)
		sources = {volumes[target]["source"].split("_")[-1] for target in ("/data", "/credentials", "/models")}
		self.assertEqual(len(sources), 3)
		# 実行時のserverは資格情報とモデルを読むだけ。書くのは設定・辞書の保存先だけ。
		self.assertTrue(volumes["/credentials"]["read_only"])
		self.assertTrue(volumes["/models"]["read_only"])
		self.assertFalse(volumes["/data"]["read_only"])
		for declared in ("server-data", "server-credentials", "server-models"):
			self.assertIn(declared, self.compose["volumes"])

	def test_tls_is_a_read_only_mount_and_no_other_bind_mounts_exist(self) -> None:
		for name in SERVICES:
			for volume in normalize_volumes(self.services[name].get("volumes", [])):
				if volume["type"] == "bind":
					self.assertEqual((name, volume["target"]), ("server", "/run/secrets/tls"))
					self.assertTrue(volume["read_only"])
				self.assertNotIn("docker.sock", str(volume["source"]))

	def test_secrets_are_not_embedded_in_config(self) -> None:
		for name in SERVICES:
			environment = environment_of(self.services[name])
			for key, value in environment.items():
				if SECRET_NAME.search(key) and "TLS_PRIVATE_KEY" not in key:
					# 値は呼び出し側の環境から渡す(未設定時はnull)。Composeに値を書かない。
					self.assertIn(value, (None, ""), f"{name}:{key}")
			for key in ("SCREEN_TRANSLATION_TLS_CERTIFICATE", "SCREEN_TRANSLATION_TLS_PRIVATE_KEY"):
				if key in environment:
					self.assertTrue(str(environment[key]).startswith("/run/secrets/tls/"), key)
		text = COMPOSE_PATH.read_text(encoding="utf-8") + ENV_EXAMPLE_PATH.read_text(encoding="utf-8")
		self.assertNotIn("BEGIN PRIVATE KEY", text)
		self.assertNotIn("BEGIN RSA PRIVATE KEY", text)
		for key, value in read_env_example().items():
			if SECRET_NAME.search(key):
				self.assertEqual(value, "", key)

	def test_only_model_preparation_has_outbound_network(self) -> None:
		self.assertEqual(self.services["prepare-model"]["network_mode"], "bridge")
		self.assertEqual(self.services["admin"]["network_mode"], "none")
		self.assertNotIn("network_mode", self.services["server"])
		self.assertEqual(self.services["prepare-model"]["profiles"], ["model"])
		self.assertEqual(self.services["admin"]["profiles"], ["admin"])


class DockerfileTest(unittest.TestCase):
	def setUp(self) -> None:
		self.text = DOCKERFILE_PATH.read_text(encoding="utf-8")

	def stage(self, name: str) -> str:
		parts = re.split(r"(?m)^FROM .* AS (\w+)$", self.text)
		stages = dict(zip(parts[1::2], parts[2::2]))
		return stages[name]

	def test_runtime_stage_is_non_root_and_does_not_ship_tests(self) -> None:
		runtime = self.stage("runtime")
		self.assertRegex(runtime, r"(?m)^USER 10001:10001$")
		self.assertNotIn("tests", runtime)
		self.assertRegex(runtime, r'(?m)^CMD \["python", "-m", "screen_translation_server"\]$')

	def test_runtime_stage_ships_the_stream_contract_the_server_validates_against(self) -> None:
		# events/__init__.pyは<ルート>/contracts/schemas/stream-message.schema.jsonを読む。無いとWSS配信が失敗する(Issue #196で実コンテナ試験が検出)。
		self.assertRegex(self.stage("runtime"), r"(?m)^COPY contracts/ \./contracts/$")

	def test_test_stage_stays_last_so_existing_test_builds_are_unchanged(self) -> None:
		stages = re.findall(r"(?m)^FROM .* AS (\w+)$", self.text)
		self.assertEqual(stages[-1], "test")
		self.assertEqual(stages.count("runtime"), 1)

	def test_image_does_not_embed_secrets_or_the_model(self) -> None:
		self.assertNotRegex(self.text, r"(?im)^(ENV|ARG)\s+\S*(TOKEN|SECRET|PASSWORD|PRIVATE_KEY)")
		self.assertNotRegex(self.text, r"(?i)COPY\s+\S*(\.env\b|\.pem|\.key|\.argosmodel)")


class ModelManifestTest(unittest.TestCase):
	def test_deployed_manifest_is_valid_and_pins_digest(self) -> None:
		manifest = ModelManifest(**json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))
		manifest.validate()
		self.assertTrue(manifest.source_url.startswith("https://"))


if __name__ == "__main__":
	unittest.main()
