"""EngineLifecycleのready状態がappへ反映される起動シーケンスを決定的に検証する。"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import httpx

from screen_translation_server import app as app_module
from screen_translation_server.app import create_app, main
from screen_translation_server.engines.lifecycle import EngineLifecycle, ModelManifest, ModelState
from screen_translation_server.lifecycle_readiness import LifecycleReadiness
from screen_translation_server.security.auth import CredentialStore, Role, SecurityPolicy
from screen_translation_server.startup import StartupConfigurationError, lifecycle_from_environment
from _api_support import DEVICE, credential, DEVICE_TOKEN, ADMIN_TOKEN, BASE_URL

# ハング防止の上限であり、同期の成否判定には使わない。
_GUARD_SECONDS = 5
SECRET_PATH = "/private/secret-dir/model"


def build_manifest() -> tuple[ModelManifest, bytes]:
	archive = io.BytesIO()
	with zipfile.ZipFile(archive, "w") as model_archive:
		model_archive.writestr("metadata.json", "{}")
	data = archive.getvalue()
	return ModelManifest(
		version="1.0", source_url="https://models.example.invalid/m.argosmodel", size_bytes=len(data),
		sha256=hashlib.sha256(data).hexdigest(), license_name="Example", license_url="https://models.example.invalid/l",
		license_accepted=True,
	), data


class StartupSequenceTest(unittest.IsolatedAsyncioTestCase):
	def setUp(self) -> None:
		self.manifest, self.model_bytes = build_manifest()
		self.directory = Path(tempfile.mkdtemp())
		self.model_path = self.directory / "translate-en_ja-1.0.argosmodel"
		self.entered = threading.Event()
		self.release = threading.Event()
		self.fail_with: Exception | None = None
		self.engines = (object(), object())
		self.sleeps: asyncio.Queue[float] = asyncio.Queue()
		self.resume: asyncio.Queue[None] = asyncio.Queue()

	def loader(self) -> object:
		self.entered.set()
		self.release.wait(30)
		if self.fail_with is not None:
			raise self.fail_with
		return self.engines

	async def next_sleep(self) -> float:
		"""再試行待ちへの到達を待つ。lifespanのstart除去などで来ない場合は無限待ちにせずassert失敗にする。"""
		try:
			return await asyncio.wait_for(self.sleeps.get(), _GUARD_SECONDS)
		except TimeoutError:
			self.fail("準備ループが再試行待ちへ到達しない(start未実行の疑い)")

	async def wait_ready(self, readiness: LifecycleReadiness) -> None:
		self.assertTrue(
			readiness.started, "準備ループが開始されていない(lifespanのstart除去の疑い)",
		)
		try:
			await asyncio.wait_for(readiness.wait_ready(), _GUARD_SECONDS)
		except TimeoutError:
			self.fail("準備が完了しない")

	async def wait_entered(self) -> None:
		self.assertTrue(await asyncio.to_thread(self.entered.wait, _GUARD_SECONDS), "準備スレッドが開始されない(start未実行の疑い)")

	async def fake_sleep(self, seconds: float) -> None:
		await self.sleeps.put(seconds)
		await self.resume.get()

	def make(self) -> tuple[LifecycleReadiness, EngineLifecycle]:
		lifecycle = EngineLifecycle(
			self.manifest, self.directory, engine_loader=self.loader, warmup=lambda _e: None,
			resource_check=lambda: True,
		)
		return LifecycleReadiness(lifecycle, sleep=self.fake_sleep), lifecycle

	def client(self, readiness: LifecycleReadiness) -> tuple[httpx.AsyncClient, object]:
		app = create_app(
			credentials=CredentialStore([credential(DEVICE_TOKEN, Role.DEVICE), credential(ADMIN_TOKEN, Role.ADMIN)]),
			policy=SecurityPolicy(frozenset({"server.example"})), readiness=readiness,
		)
		return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL), app

	async def test_preparing_then_ready_flips_ready_and_session_start(self) -> None:
		self.model_path.write_bytes(self.model_bytes)
		readiness, lifecycle = self.make()
		client, app = self.client(readiness)
		async with app.router.lifespan_context(app), client:
			await self.wait_entered()
			response = await client.get("/api/v1/ready", headers=DEVICE)
			self.assertEqual((response.status_code, response.json()["code"], response.json()["retryable"]), (503, "MODEL_NOT_READY", True))
			self.assertIn("準備中", response.json()["message"])
			started = await client.post("/api/v1/sessions", headers=DEVICE)
			self.assertEqual((started.status_code, started.json()["code"]), (503, "MODEL_NOT_READY"))
			self.assertEqual((await client.get("/api/v1/health", headers=DEVICE)).status_code, 200)
			self.release.set()
			await self.wait_ready(readiness)
			self.assertEqual(lifecycle.state, ModelState.READY)
			self.assertEqual((await client.get("/api/v1/ready", headers=DEVICE)).json(), {"ready": True})
			self.assertEqual((await client.post("/api/v1/sessions", headers=DEVICE)).status_code, 201)
			self.assertIs(readiness.engines, readiness.engines)
			self.assertEqual(readiness.engines, self.engines)

	async def test_failure_reports_safe_reason_then_recovers_automatically(self) -> None:
		self.release.set()
		readiness, lifecycle = self.make()
		client, app = self.client(readiness)
		async with app.router.lifespan_context(app), client:
			interval = await self.next_sleep()  # 未導入で失敗し、再試行待ちへ入った
			self.assertEqual(interval, 5.0)
			response = await client.get("/api/v1/ready", headers=DEVICE)
			self.assertEqual((response.status_code, response.json()["code"]), (503, "MODEL_NOT_READY"))
			self.assertIn("未導入", response.json()["message"])
			self.model_path.write_bytes(b"corrupt")
			self.resume.put_nowait(None)
			await self.next_sleep()  # 破損で再び失敗
			message = (await client.get("/api/v1/ready", headers=DEVICE)).json()["message"]
			self.assertNotIn("corrupt", message)
			self.assertEqual(lifecycle.state, ModelState.FAILED)
			self.model_path.write_bytes(self.model_bytes)
			self.resume.put_nowait(None)
			await self.wait_ready(readiness)
			self.assertEqual((await client.get("/api/v1/ready", headers=DEVICE)).status_code, 200)
			self.assertTrue(readiness.ready_event.is_set())

	async def test_failure_reason_hides_paths_and_stays_within_contract(self) -> None:
		self.model_path.write_bytes(self.model_bytes)
		self.release.set()
		self.fail_with = OSError(2, f"No such file: '{SECRET_PATH}/x'")
		readiness, _ = self.make()
		await readiness.start()
		await self.next_sleep()
		status = readiness.status()
		self.assertFalse(status.ready)
		self.assertNotIn("secret-dir", status.reason or "")
		self.assertTrue(0 < len(status.reason or "") <= 256)
		await readiness.stop()

	async def test_stop_while_preparing_returns_promptly_and_drops_ready(self) -> None:
		self.model_path.write_bytes(self.model_bytes)
		readiness, _ = self.make()
		await readiness.start()
		await self.wait_entered()
		await asyncio.wait_for(readiness.stop(), 5)  # ロード中のスレッドを待たない
		self.assertFalse(readiness.status().ready)
		self.assertIsNone(readiness.engines)
		await readiness.start()  # 停止後は再開始しない
		self.assertIsNone(readiness._task)
		self.release.set()  # スレッドを解放して後始末する

	async def test_failure_log_is_rate_limited_and_free_of_sensitive_details(self) -> None:
		self.release.set()
		self.fail_with = OSError(2, f"No such file: '{SECRET_PATH}/x'")
		readiness, _ = self.make()
		with self.assertLogs("screen_translation_server.lifecycle_readiness", level="INFO") as captured:
			await readiness.start()
			for attempt in range(1, 26):
				await self.next_sleep()
				if attempt < 25:
					self.resume.put_nowait(None)
			await readiness.stop()
		failures = [record for record in captured.records if record.getMessage().startswith("model_preparation_failed")]
		# 25回失敗しても、ログは初回・12回目・24回目の3件だけ。
		self.assertEqual([record.getMessage().rsplit("attempts=", 1)[1] for record in failures], ["1", "12", "24"])
		self.assertNotIn("secret-dir", " ".join(record.getMessage() for record in captured.records))

	async def test_recovery_after_failures_is_logged_once(self) -> None:
		self.model_path.write_bytes(self.model_bytes)
		self.release.set()
		self.fail_with = OSError("boom")
		readiness, _ = self.make()
		with self.assertLogs("screen_translation_server.lifecycle_readiness", level="INFO") as captured:
			await readiness.start()
			await self.next_sleep()
			self.fail_with = None
			self.resume.put_nowait(None)
			await self.wait_ready(readiness)
		self.assertEqual([record.getMessage() for record in captured.records][-1], "model_preparation_recovered attempts=1")

	async def test_shutdown_cancels_pending_retry(self) -> None:
		self.release.set()
		readiness, _ = self.make()
		client, app = self.client(readiness)
		async with app.router.lifespan_context(app), client:
			await self.next_sleep()
			task = readiness._task
			self.assertIsNotNone(task)
		assert task is not None
		self.assertTrue(task.done())
		self.assertFalse(readiness.status().ready)

	async def test_ready_pipeline_uses_prepared_engines_without_rebuilding(self) -> None:
		self.model_path.write_bytes(self.model_bytes)
		self.release.set()
		ocr, translator = object(), object()
		self.engines = (ocr, translator)
		readiness, _ = self.make()
		await readiness.start()
		await self.wait_ready(readiness)
		_, app = self.client(readiness)
		with patch.object(app_module, "create_pipeline_from_engines") as factory, \
			patch.object(app_module, "create_default_pipeline") as default:
			app_module._ensure_pipeline(app)
		self.assertEqual(factory.call_args.args, (ocr, translator))
		default.assert_not_called()
		await readiness.stop()


class LegacyReadyCompatibilityTest(unittest.IsolatedAsyncioTestCase):
	async def test_is_ready_flag_still_controls_ready_without_readiness(self) -> None:
		for flag, status in ((False, 503), (True, 200)):
			app = create_app(
				credentials=CredentialStore([credential(DEVICE_TOKEN, Role.DEVICE)]),
				policy=SecurityPolicy(frozenset({"server.example"})), is_ready=flag,
			)
			async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as client:
				self.assertEqual((await client.get("/api/v1/ready", headers=DEVICE)).status_code, status)
				app.state.ready = not flag  # 既存試験が行う直接代入も従来どおり効く
				self.assertEqual((await client.get("/api/v1/ready", headers=DEVICE)).status_code, 503 if flag else 200)


class MainWiringTest(unittest.TestCase):
	def test_main_builds_readiness_from_environment_and_runs_server(self) -> None:
		manifest, _ = build_manifest()
		with tempfile.TemporaryDirectory() as directory:
			manifest_path = Path(directory, "manifest.json")
			manifest_path.write_text(json.dumps(manifest.__dict__), encoding="utf-8")
			env = {"SCREEN_TRANSLATION_MODEL_MANIFEST": str(manifest_path), "SCREEN_TRANSLATION_MODEL_DIR": directory, "SCREEN_TRANSLATION_ALLOWED_HOSTS": "server.example"}
			captured: dict[str, object] = {}

			def fake_server(app, *, tls_context):
				captured["app"] = app
				return type("S", (), {"run": lambda self: captured.setdefault("ran", True)})()

			with patch.dict("os.environ", env), \
				patch.object(app_module, "create_server_tls_context_from_environment", return_value=object()), \
				patch.object(app_module, "create_server", fake_server), \
				patch.object(app_module, "_credentials_from_environment", return_value=CredentialStore([])):
				self.assertEqual(main(), 0)
		app = captured["app"]
		self.assertTrue(captured["ran"])
		self.assertIsInstance(app.state.readiness, LifecycleReadiness)  # type: ignore[attr-defined]
		self.assertFalse(app.state.readiness.status().ready)  # type: ignore[attr-defined]

	def test_main_refuses_to_start_without_model_configuration(self) -> None:
		with patch.dict("os.environ", {}, clear=True), \
			patch.object(app_module, "create_server_tls_context_from_environment", return_value=object()), \
			patch.object(app_module, "create_server") as server:
			self.assertEqual(main(), 2)
		server.assert_not_called()

	def test_invalid_manifest_error_does_not_leak_paths(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			path = Path(directory, "missing-secret.json")
			with self.assertRaises(StartupConfigurationError) as caught:
				lifecycle_from_environment({
					"SCREEN_TRANSLATION_MODEL_MANIFEST": str(path), "SCREEN_TRANSLATION_MODEL_DIR": directory,
				})
		self.assertNotIn("missing-secret", str(caught.exception))


if __name__ == "__main__":
	unittest.main()
