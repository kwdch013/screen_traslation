"""readiness指定時にpipelineを準備済みエンジン以外から作らないこと(fail-closed)を決定的に検証する (Issue #199)。

準備前・準備失敗中・停止開始後にフレームが届いても、`build_engines`の再実行(=二重ロードと
イベントループの占有)や`create_default_pipeline`への退避が起きないことを、呼び出し回数で確認する。
"""

from __future__ import annotations

import asyncio
import threading
import unittest
from unittest.mock import MagicMock, patch

from starlette.testclient import TestClient

from screen_translation_server import app as app_module
from screen_translation_server.app import create_app
from screen_translation_server.lifecycle_readiness import PipelineNotReady, ReadinessStatus
from screen_translation_server.pipeline import TranslationPipeline
from screen_translation_server.security.auth import CredentialStore, Role, SecurityPolicy
from screen_translation_server.sessions import SessionManager
from _api_support import ADMIN_TOKEN, BASE_URL, DEVICE, DEVICE_TOKEN, binary_frame, credential

# ハング防止の上限であり、同期の成否判定には使わない。
_GUARD_SECONDS = 10
_STATES = {
	"preparing": ReadinessStatus(False, "モデルと翻訳エンジンを準備中です。"),
	"failed": ReadinessStatus(False, "モデルと翻訳エンジンの準備に失敗しました。"),
	"stopping": ReadinessStatus(False, "サーバーを停止しています。"),
	# 供給元が矛盾して、readyなのにエンジンを返さない場合も既定構成へ退避しない。
	"ready_without_engines": ReadinessStatus(True),
}


class FakeReadiness:
	"""状態を試験が直接切り替えられるReadinessSource。"""

	def __init__(self, status: ReadinessStatus, engines: tuple[object, object] | None = None) -> None:
		self._status = status
		self._engines = engines
		self.started = 0
		self.stopped = 0

	def set(self, status: ReadinessStatus, engines: tuple[object, object] | None = None) -> None:
		self._status, self._engines = status, engines

	def status(self) -> ReadinessStatus:
		return self._status

	@property
	def engines(self) -> tuple[object, object] | None:
		return self._engines if self._status.ready else None

	async def start(self) -> None:
		self.started += 1

	async def stop(self) -> None:
		self.stopped += 1


def make_app(readiness: FakeReadiness, **options: object):
	return create_app(
		credentials=CredentialStore([credential(DEVICE_TOKEN, Role.DEVICE), credential(ADMIN_TOKEN, Role.ADMIN)]),
		policy=SecurityPolicy(frozenset({"server.example"})), readiness=readiness,
		sessions=SessionManager(clock=lambda: 1.0, sleep=asyncio.sleep), **options,  # type: ignore[arg-type]
	)


class NoFallbackTest(unittest.TestCase):
	def setUp(self) -> None:
		self.default = patch.object(app_module, "create_default_pipeline", side_effect=AssertionError("フォールバック禁止"))
		self.build = patch("screen_translation_server.engines.build_engines", side_effect=AssertionError("build_engines再実行禁止"))
		self.default_mock, self.build_mock = self.default.start(), self.build.start()
		self.addCleanup(self.default.stop)
		self.addCleanup(self.build.stop)

	def test_ensure_pipeline_refuses_without_engines_in_every_not_ready_state(self) -> None:
		for name, status in _STATES.items():
			with self.subTest(state=name):
				app = make_app(FakeReadiness(status))
				with self.assertRaises(PipelineNotReady):
					app_module._ensure_pipeline(app)
				self.assertIsNone(app.state.pipeline)
		self.default_mock.assert_not_called()
		self.build_mock.assert_not_called()

	def test_ensure_pipeline_refuses_existing_pipeline_once_readiness_is_lost(self) -> None:
		readiness = FakeReadiness(ReadinessStatus(True), (object(), object()))
		app = make_app(readiness)
		with patch.object(app_module, "create_pipeline_from_engines", return_value=MagicMock(spec=TranslationPipeline)) as factory:
			self.assertIsNotNone(app_module._ensure_pipeline(app))
			factory.assert_called_once()
			readiness.set(_STATES["stopping"])
			with self.assertRaises(PipelineNotReady):
				app_module._ensure_pipeline(app)
			factory.assert_called_once()  # 再構築もしない

	def test_legacy_path_without_readiness_still_builds_default_pipeline(self) -> None:
		with patch.object(app_module, "create_default_pipeline", return_value=MagicMock(spec=TranslationPipeline)) as default:
			app = create_app(
				credentials=CredentialStore([credential(DEVICE_TOKEN, Role.DEVICE)]),
				policy=SecurityPolicy(frozenset({"server.example"})), is_ready=True,
			)
			app_module._ensure_pipeline(app)
		default.assert_called_once()

	def frame_is_rejected_with_model_not_ready(self, name: str) -> None:
		readiness = FakeReadiness(ReadinessStatus(True), (object(), object()))
		app = make_app(readiness)
		published = threading.Event()
		original = app.state.events.publish_error

		def spy(*args: object, **kwargs: object) -> None:
			original(*args, **kwargs)
			if args and args[0] == "MODEL_NOT_READY":
				published.set()

		app.state.events.publish_error = spy
		with TestClient(app, base_url=BASE_URL) as client:
			session = client.post("/api/v1/sessions", headers=DEVICE, json={}).json()
			readiness.set(_STATES[name])  # セッション開始後に準備が失われた
			with client.websocket_connect("wss://server.example/api/v1/stream", headers=DEVICE) as websocket:
				websocket.send_bytes(binary_frame(session, 1, session["dictionary_revision"]))
				self.assertTrue(published.wait(_GUARD_SECONDS), "MODEL_NOT_READYが通知されない")
				received = []
				while not received or received[-1]["type"] != "error":  # 通知は発行済みなので必ず届く
					received.append(websocket.receive_json())
				self.assertEqual((received[-1]["code"], received[-1]["frame_id"]), ("MODEL_NOT_READY", 1))
				# 拒否したフレームを処理中として通知しない。
				self.assertNotIn("processing", [item.get("state") for item in received])
		self.default_mock.assert_not_called()
		self.build_mock.assert_not_called()
		self.assertIsNone(app.state.pipeline)

	def test_frames_before_ready_failed_or_stopping_are_rejected_without_rebuilding(self) -> None:
		for name in _STATES:
			with self.subTest(state=name):
				self.frame_is_rejected_with_model_not_ready(name)


class LifespanContractTest(unittest.IsolatedAsyncioTestCase):
	async def test_lifespan_starts_and_stops_readiness_exactly_once(self) -> None:
		"""start除去を無限待ちではなくassert失敗として即座に検出する。"""
		readiness = FakeReadiness(ReadinessStatus(False, "準備中"))
		app = make_app(readiness)
		async with app.router.lifespan_context(app):
			self.assertEqual((readiness.started, readiness.stopped), (1, 0))
		self.assertEqual((readiness.started, readiness.stopped), (1, 1))


if __name__ == "__main__":
	unittest.main()
