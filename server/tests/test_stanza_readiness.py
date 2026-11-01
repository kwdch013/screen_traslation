"""Stanza資源が未準備・破損のとき、準備失敗としてreadinessへ反映され、翻訳要求が拒否されることを確認する。"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

import httpx

from _api_support import ADMIN_TOKEN, BASE_URL, DEVICE, DEVICE_TOKEN, credential
from screen_translation_server.app import create_app
from screen_translation_server.engines.lifecycle import EngineLifecycle, ModelState
from screen_translation_server.engines.stanza_resources import StanzaResources
from screen_translation_server.lifecycle_readiness import LifecycleReadiness
from screen_translation_server.security.auth import CredentialStore, Role, SecurityPolicy
from test_lifecycle_readiness import build_manifest
from test_stanza_resources import CONTENTS, FakeDownloader, build_manifest as build_stanza_manifest

_GUARD_SECONDS = 5


class StanzaReadinessTest(unittest.IsolatedAsyncioTestCase):
	def setUp(self) -> None:
		self.manifest, model_bytes = build_manifest()
		root = Path(tempfile.mkdtemp())
		self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
		self.models = root / "models"
		self.models.mkdir()
		(self.models / "translate-en_ja-1.0.argosmodel").write_bytes(model_bytes)
		self.stanza_directory = root / "stanza-secret"
		self.stanza = StanzaResources(build_stanza_manifest(), lambda: self.stanza_directory)
		self.loaded = 0
		self.sleeps: asyncio.Queue[float] = asyncio.Queue()
		self.resume: asyncio.Queue[None] = asyncio.Queue()

	def loader(self) -> object:
		self.loaded += 1
		return (object(), object())

	async def fake_sleep(self, seconds: float) -> None:
		await self.sleeps.put(seconds)
		await self.resume.get()

	def lifecycle(self) -> EngineLifecycle:
		return EngineLifecycle(
			self.manifest, self.models, engine_loader=self.loader, warmup=lambda _e: None,
			resource_check=lambda: True, stanza_resources=self.stanza,
		)

	def client(self, readiness: LifecycleReadiness) -> tuple[httpx.AsyncClient, object]:
		app = create_app(
			credentials=CredentialStore([credential(DEVICE_TOKEN, Role.DEVICE), credential(ADMIN_TOKEN, Role.ADMIN)]),
			policy=SecurityPolicy(frozenset({"server.example"})), readiness=readiness,
		)
		return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL), app

	def test_lifecycle_fails_before_loading_engines_when_resources_are_missing(self) -> None:
		lifecycle = self.lifecycle()
		with self.assertRaises(Exception):
			lifecycle.prepare()
		self.assertEqual(lifecycle.state, ModelState.FAILED)
		self.assertEqual(self.loaded, 0)  # 資源が無いのにエンジン(=外部取得の恐れ)を読み込まない
		self.assertIn("Stanza資源", lifecycle.failure_reason or "")
		self.assertNotIn("stanza-secret", lifecycle.failure_reason or "")

	def test_lifecycle_becomes_ready_when_resources_are_valid(self) -> None:
		self.stanza.provision(downloader=FakeDownloader())
		lifecycle = self.lifecycle()
		lifecycle.prepare()
		self.assertEqual(lifecycle.state, ModelState.READY)

	def test_corrupt_resource_after_ready_blocks_next_preparation(self) -> None:
		self.stanza.provision(downloader=FakeDownloader())
		(self.stanza_directory / "en/mwt/combined.pt").write_bytes(b"x" * len(CONTENTS["en/mwt/combined.pt"]))
		lifecycle = self.lifecycle()
		with self.assertRaises(Exception):
			lifecycle.prepare()
		self.assertIn("破損", lifecycle.failure_reason or "")

	async def test_requests_are_rejected_until_resources_are_prepared_then_recover(self) -> None:
		readiness = LifecycleReadiness(self.lifecycle(), sleep=self.fake_sleep)
		client, app = self.client(readiness)
		async with app.router.lifespan_context(app), client:
			await asyncio.wait_for(self.sleeps.get(), _GUARD_SECONDS)  # 失敗し再試行待ちへ入った
			ready = await client.get("/api/v1/ready", headers=DEVICE)
			self.assertEqual((ready.status_code, ready.json()["code"], ready.json()["retryable"]), (503, "MODEL_NOT_READY", True))
			self.assertIn("Stanza資源", ready.json()["message"])
			self.assertNotIn("stanza-secret", ready.json()["message"])
			started = await client.post("/api/v1/sessions", headers=DEVICE)
			self.assertEqual((started.status_code, started.json()["code"]), (503, "MODEL_NOT_READY"))
			self.assertEqual((await client.get("/api/v1/health", headers=DEVICE)).status_code, 200)
			self.assertEqual(self.loaded, 0)
			self.stanza.provision(downloader=FakeDownloader())  # 管理者が資源準備を実行した
			self.resume.put_nowait(None)
			await asyncio.wait_for(readiness.wait_ready(), _GUARD_SECONDS)
			self.assertEqual((await client.get("/api/v1/ready", headers=DEVICE)).status_code, 200)
			self.assertEqual((await client.post("/api/v1/sessions", headers=DEVICE)).status_code, 201)


if __name__ == "__main__":
	unittest.main()
