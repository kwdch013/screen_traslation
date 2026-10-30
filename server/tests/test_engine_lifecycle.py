from __future__ import annotations

import hashlib
import importlib.util
import io
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from screen_translation_server.engines.lifecycle import (
	EngineLifecycle,
	INSTALLED_START_TIMEOUT_SECONDS,
	LatestFrameBuffer,
	ModelManifest,
	ModelProvisioner,
	ModelState,
	PREPARATION_TIMEOUT_SECONDS,
	ProcessingGate,
	ResourceLimits,
)
from screen_translation_server.readiness import health_response, ready_response


class FakeClock:
	def __init__(self) -> None:
		self.now = 100.0

	def monotonic(self) -> float:
		return self.now

	def advance(self, seconds: float) -> None:
		self.now += seconds


class EngineLifecycleTest(unittest.TestCase):
	def setUp(self) -> None:
		archive = io.BytesIO()
		with zipfile.ZipFile(archive, "w") as model_archive:
			model_archive.writestr("metadata.json", "{}")
		self.model_bytes = archive.getvalue()
		self.manifest = ModelManifest(
			version="1.0",
			source_url="https://models.example.invalid/en-ja.argosmodel",
			size_bytes=len(self.model_bytes),
			sha256=hashlib.sha256(self.model_bytes).hexdigest(),
			license_name="Example License",
			license_url="https://models.example.invalid/license",
			license_accepted=True,
		)

	def test_health_is_alive_while_engine_is_not_ready(self) -> None:
		lifecycle = EngineLifecycle(self.manifest, tempfile.mkdtemp())

		self.assertEqual(health_response(lifecycle), (200, {"status": "alive"}))
		status, response = ready_response(lifecycle)
		self.assertEqual(status, 503)
		self.assertEqual(response["code"], "MODEL_NOT_READY")
		self.assertEqual(lifecycle.state, ModelState.MISSING)

	def test_ready_after_model_verification_and_warmup(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			Path(directory, "translate-en_ja-1.0.argosmodel").write_bytes(self.model_bytes)
			loads: list[str] = []
			lifecycle = EngineLifecycle(
				self.manifest,
				directory,
				engine_loader=lambda: loads.append("load") or object(),
				warmup=lambda _engine: None,
			)

			lifecycle.prepare()
			lifecycle.prepare()

			self.assertEqual(lifecycle.state, ModelState.READY)
			self.assertEqual(ready_response(lifecycle), (200, {"ready": True}))
			self.assertEqual(loads, ["load"])

	def test_failure_stays_not_ready_and_reports_safe_reason(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			Path(directory, "translate-en_ja-1.0.argosmodel").write_bytes(self.model_bytes)
			lifecycle = EngineLifecycle(
				self.manifest,
				directory,
				engine_loader=lambda: object(),
				warmup=lambda _engine: (_ for _ in ()).throw(RuntimeError("warmup failed")),
			)

			with self.assertRaises(RuntimeError):
				lifecycle.prepare()

			self.assertEqual(lifecycle.state, ModelState.FAILED)
			self.assertFalse(lifecycle.ready_response()["ready"])
			self.assertEqual(lifecycle.failure_reason, "warmup failed")

	def test_model_provisioner_checks_license_and_digest_before_install(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			calls: list[Path] = []
			progress: list[str] = []
			provisioner = ModelProvisioner(
				self.manifest,
				Path(directory),
				downloader=lambda _url, target, _timeout: target.write_bytes(self.model_bytes),
				installer=lambda model_path: calls.append(model_path),
				progress=progress.append,
			)
			result = provisioner.provision()

			self.assertEqual(result, Path(directory, "translate-en_ja-1.0.argosmodel"))
			self.assertEqual(len(calls), 1)
			self.assertEqual(result.read_bytes(), self.model_bytes)
			self.assertEqual(progress, ["downloading", "verifying", "installing", "complete"])
			self.assertEqual(provisioner.progress, "complete")
			self.assertIsNone(provisioner.failure_reason)

	def test_provisioner_install_over_deadline_fails_without_completing(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			clock = FakeClock()
			attempts = 0

			def install(_model_path: Path) -> None:
				nonlocal attempts
				attempts += 1
				if attempts == 1:
					clock.advance(0.05)

			provisioner = ModelProvisioner(
				self.manifest,
				Path(directory),
				downloader=lambda _url, target, _timeout: target.write_bytes(self.model_bytes),
				installer=install,
				monotonic=clock.monotonic,
			)
			deadline = clock.monotonic() + 0.01

			with self.assertRaisesRegex(TimeoutError, "期限を超過"):
				provisioner.provision(deadline=deadline)
			self.assertEqual(provisioner.progress, "failed")
			self.assertIn("期限を超過", provisioner.failure_reason or "")
			self.assertTrue(provisioner.model_path.exists())

			provisioner.provision()

			self.assertEqual(provisioner.progress, "complete")
			self.assertIsNone(provisioner.failure_reason)

	def test_existing_model_install_over_deadline_does_not_complete(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			model_path = Path(directory, "translate-en_ja-1.0.argosmodel")
			model_path.write_bytes(self.model_bytes)
			clock = FakeClock()
			provisioner = ModelProvisioner(
				self.manifest,
				Path(directory),
				installer=lambda _path: clock.advance(0.05),
				monotonic=clock.monotonic,
			)

			with self.assertRaisesRegex(TimeoutError, "期限を超過"):
				provisioner.provision(deadline=clock.monotonic() + 0.01)

			self.assertEqual(provisioner.progress, "failed")
			self.assertFalse(provisioner.progress == "complete")
			self.assertTrue(model_path.exists())

	def test_prepare_deadline_is_checked_after_warmup(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			Path(directory, "translate-en_ja-1.0.argosmodel").write_bytes(self.model_bytes)
			clock = FakeClock()
			lifecycle = EngineLifecycle(
				self.manifest,
				directory,
				engine_loader=lambda: object(),
				warmup=lambda _engine: clock.advance(0.02),
				monotonic=clock.monotonic,
			)

			with self.assertRaisesRegex(TimeoutError, "期限を超過"):
				lifecycle.prepare(deadline=clock.monotonic() + 0.01)

			self.assertEqual(lifecycle.state, ModelState.FAILED)
			self.assertEqual(lifecycle.progress, "failed")
			self.assertIn("期限を超過", lifecycle.failure_reason or "")
			self.assertFalse(lifecycle.ready_response()["ready"])

	def test_failure_then_retry_success_clears_previous_failure_reason(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			attempts = 0

			def install(_model_path: Path) -> None:
				nonlocal attempts
				attempts += 1
				if attempts == 1:
					raise RuntimeError("installation failed")

			provisioner = ModelProvisioner(
				self.manifest,
				Path(directory),
				downloader=lambda _url, target, _timeout: target.write_bytes(self.model_bytes),
				installer=install,
			)
			with self.assertRaisesRegex(RuntimeError, "installation failed"):
				provisioner.provision()
			self.assertEqual(provisioner.progress, "failed")
			self.assertEqual(provisioner.failure_reason, "installation failed")

			provisioner.provision()

			self.assertEqual(provisioner.progress, "complete")
			self.assertIsNone(provisioner.failure_reason)

	def test_download_failure_does_not_activate_unverified_model(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			provisioner = ModelProvisioner(
				self.manifest,
				Path(directory),
				downloader=lambda _url, target, _timeout: target.write_bytes(b"tampered"),
				installer=lambda _path: self.fail("不正モデルを導入してはいけない"),
			)
			with self.assertRaises(ValueError):
				provisioner.provision()

			self.assertEqual(provisioner.progress, "failed")
			self.assertFalse(provisioner.model_path.exists())

	def test_model_with_unaccepted_license_is_rejected(self) -> None:
		manifest = ModelManifest(
			**{**self.manifest.__dict__, "license_accepted": False}
		)
		with tempfile.TemporaryDirectory() as directory:
			provisioner = ModelProvisioner(manifest, Path(directory))
			with self.assertRaises(ValueError):
				provisioner.provision()

	def test_resource_limits_reject_excessive_runtime_budget(self) -> None:
		limits = ResourceLimits()
		self.assertTrue(limits.validate(cpu_count=2, memory_bytes=4 * 1024**3))
		self.assertFalse(limits.validate(cpu_count=3, memory_bytes=4 * 1024**3))
		self.assertFalse(limits.validate(cpu_count=2, memory_bytes=4 * 1024**3 + 1))

	def test_resource_limits_read_cgroup_quota_and_memory_ceiling(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			root = Path(directory)
			(root / "cpu.max").write_text("200000 100000", encoding="ascii")
			(root / "memory.max").write_text(str(4 * 1024**3), encoding="ascii")
			self.assertTrue(ResourceLimits().validate_runtime(root))
			(root / "cpu.max").write_text("300000 100000", encoding="ascii")
			self.assertFalse(ResourceLimits().validate_runtime(root))

	def test_resource_overflow_keeps_engine_not_ready(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			Path(directory, "translate-en_ja-1.0.argosmodel").write_bytes(self.model_bytes)
			lifecycle = EngineLifecycle(
				self.manifest,
				directory,
				engine_loader=lambda: self.fail("資源超過時はエンジンをロードしない"),
				resource_check=lambda: False,
			)
			with self.assertRaises(RuntimeError):
				lifecycle.prepare()
			self.assertEqual(lifecycle.state, ModelState.FAILED)
			self.assertFalse(lifecycle.ready_response()["ready"])

	def test_preparation_timeout_budgets_match_the_adopted_requirements(self) -> None:
		self.assertEqual(PREPARATION_TIMEOUT_SECONDS, 1800)
		self.assertEqual(INSTALLED_START_TIMEOUT_SECONDS, 120)

	def test_latest_waiting_frame_replaces_older_frame(self) -> None:
		buffer = LatestFrameBuffer()
		buffer.submit("frame-1")
		buffer.submit("frame-2")
		self.assertEqual(buffer.take(), "frame-2")
		self.assertIsNone(buffer.take())

	def test_processing_gate_rejects_parallel_work(self) -> None:
		gate = ProcessingGate()
		self.assertTrue(gate.submit("frame-1"))
		self.assertFalse(gate.submit("frame-2"))
		self.assertFalse(gate.submit("frame-3"))
		self.assertEqual(gate.release(), "frame-3")
		self.assertIsNone(gate.release())

	@unittest.skipUnless(
		shutil.which("tesseract") and importlib.util.find_spec("argostranslate"),
		"実エンジン依存がない環境ではskip",
	)
	def test_real_engines_smoke_when_model_is_installed(self) -> None:
		from argostranslate import translate

		languages = {language.code for language in translate.get_installed_languages()}
		if not {"en", "ja"}.issubset(languages):
			self.skipTest("Argos英日モデルが導入されていません")
		from screen_translation_server.engines import build_engines

		ocr, translator = build_engines()
		ocr.validate()
		self.assertTrue(translator.translate("Hello"))


if __name__ == "__main__":
	unittest.main()
