"""実エンジン結合試験の共通TestCase。実エンジンは1プロセスで1度だけ準備する。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import time
from typing import Any
import unittest

from pipeline_support import (
	GatedOcr,
	engine_versions,
	model_directory,
	read_until,
	require_model,
	use_installed_stanza_resources,
)
from screen_translation_server.engines.lifecycle import EngineLifecycle, ModelManifest
from screen_translation_server.lifecycle_readiness import ReadinessSource
from screen_translation_server.pipeline import TranslationPipeline
from screen_translation_server.sessions import SessionManager
from live_server import LiveServer


@dataclass(frozen=True)
class RealEngines:
	manifest: ModelManifest
	ocr: Any
	translator: Any
	versions: dict[str, str]
	lifecycle: EngineLifecycle


_ENGINES: RealEngines | None = None


def real_engines() -> RealEngines:
	"""モデル検証・資源上限・warmupを含むEngineLifecycleで実Tesseract/Argosを準備する。"""
	global _ENGINES
	if _ENGINES is None:
		manifest = require_model()
		use_installed_stanza_resources()
		lifecycle = EngineLifecycle(manifest, model_directory())
		ocr, translator = lifecycle.prepare()  # type: ignore[misc]
		_ENGINES = RealEngines(manifest, ocr, translator, engine_versions(manifest), lifecycle)
	return _ENGINES


class PipelineCase(unittest.TestCase):
	"""試験ごとに実TLS server・実pipelineを起動し、終了時に必ず解放する。"""

	engines: RealEngines

	@classmethod
	def setUpClass(cls) -> None:
		cls.engines = real_engines()

	def make_server(
		self, ocr: Any = None, *, observer: Any = None, readiness: ReadinessSource | None = None,
	) -> LiveServer:
		sessions = SessionManager(clock=time.monotonic, sleep=asyncio.sleep, disconnect_timeout=60)
		pipeline = TranslationPipeline(
			ocr or self.engines.ocr, self.engines.translator, clock=time.monotonic,
			is_current=sessions.is_current, observer=observer,
		)
		server = LiveServer(pipeline, sessions, is_ready=readiness is None, readiness=readiness)
		self.addCleanup(server.close)
		return server

	def open_session(self, server: LiveServer) -> tuple[dict[str, Any], Any]:
		"""session開始→WSS接続→accepted/readyの受信までを済ませる。呼び出し側がwith/closeする。"""
		response = server.start_session()
		self.assertEqual(response.status_code, 201)
		session = response.json()
		websocket = server.websocket()
		websocket.__enter__()
		self.addCleanup(websocket.__exit__, None, None, None)
		read_until(websocket, lambda message: message["type"] == "state" and message["state"] == "ready")
		return session, websocket

	def settle(self, server: LiveServer) -> None:
		"""購読・worker・待機画像・session・streamが残っていないことを確認する。

		サーバーloop内で状態変化を待つ。timeoutは終了しない場合の失敗検出専用。
		"""
		async def wait_released() -> dict[str, int]:
			# pipelineは最初のframeで作られるため、frameを送らなかった試験ではNoneのまま。
			def workers() -> int:
				return server.pipeline.active_worker_count if server.pipeline is not None else 0

			async with asyncio.timeout(60):
				await server.app.state.events.wait_until_empty()
				while workers() or server.sessions._active is not None or server.app.state.streams:
					await asyncio.sleep(0.01)
			pipeline = server.pipeline
			return {
				"subscribers": server.app.state.events.subscriber_count_total,
				"workers": workers(),
				"pending": pipeline.pending_frame_count if pipeline is not None else 0,
				"published": len(pipeline.published_results) if pipeline is not None else 0,
				"streams": len(server.app.state.streams),
			}
		residue = server.run(wait_released(), timeout=90)
		self.assertEqual(residue, dict.fromkeys(("subscribers", "workers", "pending", "published", "streams"), 0))


def gated(engines: RealEngines) -> GatedOcr:
	return GatedOcr(engines.ocr)
