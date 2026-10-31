"""サーバー全体の結合シナリオ試験の共通部品(再起動・ログ捕捉・同期用の道具)。"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any
import unittest.mock

import httpx

from live_server import LiveServer, Site
from pipeline_case import PipelineCase
from pipeline_support import load_cases, model_directory
from readiness_support import RetryGate, WAIT_SECONDS
from screen_translation_server.engines.lifecycle import EngineLifecycle
from screen_translation_server.lifecycle_readiness import LifecycleReadiness
from screen_translation_server.observability import ProcessingObserver
from screen_translation_server.pipeline import TranslationPipeline
from screen_translation_server.sessions import SessionManager

GLOSSARY_TARGET = "辞書訳シナリオ試験"
CLEAR_CASE = next(case for case in load_cases() if case["id"] == "clear-01")


class RecordingObserver(ProcessingObserver):
	"""破棄通知を数え、指定件数に達するまで待てる観測器(固定sleepを使わない同期用)。"""

	def __init__(self) -> None:
		super().__init__()
		self._condition = threading.Condition()
		self.counts: dict[str, int] = {}

	def dropped(self, stage: str, *, correlation_id: str, count: int = 1) -> None:
		super().dropped(stage, correlation_id=correlation_id, count=count)
		with self._condition:
			self.counts[stage] = self.counts.get(stage, 0) + count
			self._condition.notify_all()

	def wait_for(self, stage: str, count: int, timeout: float = 120) -> bool:
		with self._condition:
			return self._condition.wait_for(lambda: self.counts.get(stage, 0) >= count, timeout)


class LogCapture(logging.Handler):
	"""全loggerのrecordを集め、message・extra・例外を1つの文字列にして漏えいを検査する。"""

	def __init__(self) -> None:
		super().__init__(logging.DEBUG)
		self.records: list[logging.LogRecord] = []

	# 試験クライアント側のライブラリはDEBUGで自分の送信ヘッダー(Authorization)を出す。サーバーのログではないため除く。
	# argostranslateはINFOで訳文を出し、運用側がrootにhandlerを足すと漏れる第三者の既知課題。
	# 製品側の対処はdocs/v1.0/testing.mdの「未解決事項」に記録し、本試験は自サーバーの出力を検査する。
	CLIENT_LOGGERS = ("websockets.client", "httpx", "httpcore")
	THIRD_PARTY_LOGGERS = ("argostranslate",)

	def emit(self, record: logging.LogRecord) -> None:
		if not record.name.startswith(self.CLIENT_LOGGERS + self.THIRD_PARTY_LOGGERS):
			self.records.append(record)

	def text(self, *, exclude: tuple[str, ...] = ()) -> str:
		parts: list[str] = []
		for record in self.records:
			if record.name in exclude:
				continue
			parts.append(record.getMessage())
			parts.append(repr(record.__dict__))
			if record.exc_info:
				parts.append(logging.Formatter().formatException(record.exc_info))
		return "\n".join(parts)


class ScenarioCase(PipelineCase):
	"""試験ごとにログ捕捉を始め、再起動(同じSiteで新しいLiveServer)を起こせる。"""

	def setUp(self) -> None:
		self.logs = LogCapture()
		self._loggers = [logging.getLogger(), logging.getLogger("uvicorn"), logging.getLogger("uvicorn.access")]
		own = logging.getLogger("screen_translation_server")
		levels = [(logging.getLogger(), logging.getLogger().level), (own, own.level)]
		for logger in self._loggers:
			logger.addHandler(self.logs)
		# 運用の既定(INFO)で出る全ログと、自サーバーのDEBUGまでを検査する。
		logging.getLogger().setLevel(logging.INFO)
		own.setLevel(logging.DEBUG)

		def restore() -> None:
			for logger in self._loggers:
				logger.removeHandler(self.logs)
			for logger, level in levels:
				logger.setLevel(level)
		self.addCleanup(restore)

	def shared_lifecycle(self, directory: Any = None, hold: threading.Event | None = None) -> EngineLifecycle:
		"""実モデルの検証・資源上限確認を通し、重いロードだけ共有済みの実エンジンで置き換えるEngineLifecycle。

		holdを渡すと、そのEventが立つまでロードを保留して「準備中」を観測できる。
		"""
		def load() -> object:
			if hold is not None:
				hold.wait(WAIT_SECONDS)
			return (self.engines.ocr, self.engines.translator)

		return EngineLifecycle(
			self.engines.manifest, directory or model_directory(), engine_loader=load, warmup=lambda _engine: None,
		)

	def start(
		self,
		site: Site | None = None,
		*,
		ocr: Any = None,
		lifecycle: EngineLifecycle | None = None,
		gate: RetryGate | None = None,
	) -> LiveServer:
		"""本番と同じ経路(環境変数の保存先・EngineLifecycleのready反映・遅延pipeline生成・辞書wrapper)で起動する。

		lifecycleを渡した場合は準備完了を待たずに返す(準備中・失敗を観測するため)。渡さなければ
		準備済みのlifecycleを使い、ready反映まで待ってから返す。

		実エンジンは重いため共有し、pipeline生成だけを差し替える。再起動ごとにSession・辞書・
		キャッシュ・pipelineは新しくなる。
		"""
		def build_pipeline(**options: Any) -> TranslationPipeline:
			wrap = options.pop("translator_wrapper")
			return TranslationPipeline(ocr or self.engines.ocr, wrap(self.engines.translator), **options)

		def build_from_engines(prepared_ocr: Any, translator: Any, **options: Any) -> TranslationPipeline:
			wrap = options.pop("translator_wrapper")
			return TranslationPipeline(ocr or prepared_ocr, wrap(translator), **options)

		for name, replacement in (("create_default_pipeline", build_pipeline), ("create_pipeline_from_engines", build_from_engines)):
			patcher = unittest.mock.patch(f"screen_translation_server.app.{name}", side_effect=replacement)
			patcher.start()
			self.addCleanup(patcher.stop)
		readiness = LifecycleReadiness(
			lifecycle or self.shared_lifecycle(), sleep=gate.sleep if gate else asyncio.sleep, retry_interval=0.05,
		)
		sessions = SessionManager(clock=time.monotonic, sleep=asyncio.sleep, disconnect_timeout=60)
		server = LiveServer(None, sessions, site=site, readiness=readiness)
		self.addCleanup(server.close)
		if lifecycle is None:
			self.assertTrue(readiness.started, "準備ループが開始されていない(lifespanのstart除去の疑い)")
			self.assertTrue(readiness.ready_event.wait(WAIT_SECONDS))
		# uvicornのConfigがloggingを再設定してhandlerを外すため、起動のたびに付け直す。
		for logger in self._loggers:
			if self.logs not in logger.handlers:
				logger.addHandler(self.logs)
		server.observer = RecordingObserver()  # type: ignore[attr-defined]
		server.app.state.observer = server.observer  # type: ignore[attr-defined]
		return server

	def get(self, server: LiveServer, path: str, *, admin: bool = False) -> httpx.Response:
		return server.client.get(path, headers=server.admin_headers() if admin else server.headers())

	def put(self, server: LiveServer, path: str, body: object, revision: int) -> httpx.Response:
		return server.client.put(path, json=body, headers={**server.admin_headers(), "If-Match": f'"{revision}"'})

	def put_glossary(self, server: LiveServer, source: str, target: str, revision: int) -> httpx.Response:
		return self.put(server, "/api/v1/glossary", {"entries": [{"source": source, "target": target}]}, revision)

	def wait_until_no_session(self, server: LiveServer) -> None:
		"""サーバーloop内で、切断によるsession解放を状態変化で待つ(timeoutは失敗検出専用)。"""
		async def wait() -> None:
			async with asyncio.timeout(60):
				while server.sessions._active is not None:
					await asyncio.sleep(0.01)
		server.run(wait(), timeout=90)

	def assert_not_logged(self, *secrets: str, exclude: tuple[str, ...] = ()) -> None:
		text = self.logs.text(exclude=exclude)
		for index, secret in enumerate(secrets):
			self.assertTrue(secret)
			# 失敗時に秘密値やログ全体を出力へ複製しない。
			self.assertFalse(secret in text, f"{index}番目の秘密値がログに含まれています。")
