"""実TLS listenerで本物のappを起動する結合試験用ハーネス。

試験ごとに一時CA・証明書・資格情報を生成して破棄し、鍵や固定の接続先はリポジトリへ置かない。
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
import logging
import os
from pathlib import Path
import secrets
import socket
import ssl
import subprocess
import tempfile
import threading
import time
from typing import Any
import unittest.mock

import httpx
from starlette.applications import Starlette

from screen_translation_server.admin.credentials import CredentialManager
from screen_translation_server.app import create_app, create_server
from screen_translation_server.pipeline import TranslationPipeline
from screen_translation_server.security.auth import (
	CredentialStore,
	Role,
	SecurityPolicy,
	create_credential,
	create_server_tls_context,
)
from screen_translation_server.sessions import SessionManager
from ws_client import SyncWebSocket


class LiveServer:
	"""loopbackのTLSで待ち受けるappと、同じ信頼設定のHTTP/WSSクライアントを提供する。"""

	def __init__(self, pipeline: TranslationPipeline, sessions: SessionManager, *, is_ready: bool = True) -> None:
		self._temporary = tempfile.TemporaryDirectory(prefix="screen-translation-pipeline-")
		self.directory = Path(self._temporary.name)
		self.token = secrets.token_hex(32)
		self.sessions = sessions
		self.pipeline = pipeline
		with socket.socket() as listener:
			listener.bind(("127.0.0.1", 0))
			self.port = int(listener.getsockname()[1])
		self._make_certificates()
		manager = CredentialManager(self.directory / "credentials.json")
		manager._write([create_credential(
			self.token, Role.DEVICE, datetime.now(UTC) + timedelta(hours=1), "device-pipeline",
		)])
		self.app: Starlette = create_app(
			credentials=CredentialStore.from_file(self.directory / "credentials.json"),
			policy=SecurityPolicy(frozenset({f"127.0.0.1:{self.port}"})),
			is_ready=is_ready,
			sessions=sessions,
			pipeline=pipeline,
		)
		self._environment = unittest.mock.patch.dict(os.environ, {
			"SCREEN_TRANSLATION_BIND_HOST": "127.0.0.1",
			"SCREEN_TRANSLATION_PORT": str(self.port),
		})
		self._environment.start()
		# accessログのURLにsession_idが載るため、試験出力へは出さない。
		logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
		self.server = create_server(self.app, tls_context=create_server_tls_context(
			self.directory / "server.pem", self.directory / "server.key",
		))
		self._loop_ready = threading.Event()
		self._thread = threading.Thread(target=self._serve, daemon=True)
		self._thread.start()
		self._wait_started()
		self.client = httpx.Client(
			base_url=f"https://127.0.0.1:{self.port}", verify=self.trusted_context(), trust_env=False, timeout=10,
		)

	def _serve(self) -> None:
		async def serve() -> None:
			self.loop = asyncio.get_running_loop()
			self._loop_ready.set()
			await self.server.serve()
		asyncio.run(serve())

	def _wait_started(self) -> None:
		# listener開始はuvicornのstartedフラグで同期する。上限は無応答時の失敗検出専用。
		deadline = time.monotonic() + 30
		while not self.server.started:
			if time.monotonic() > deadline or not self._thread.is_alive():
				raise RuntimeError("TLS listenerが起動しませんでした。")
			self._loop_ready.wait(0.05)

	def _make_certificates(self) -> None:
		directory = self.directory

		def openssl(*arguments: object) -> None:
			result = subprocess.run(["openssl", *map(str, arguments)], capture_output=True, text=True, check=False)
			if result.returncode:
				raise RuntimeError(f"openssl failed: {result.stderr[-300:]}")

		openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", directory / "ca.key",
			"-out", directory / "ca.pem", "-days", "2", "-subj", "/CN=Pipeline Test CA",
			"-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,keyCertSign,cRLSign")
		openssl("req", "-newkey", "rsa:2048", "-nodes", "-keyout", directory / "server.key",
			"-out", directory / "server.csr", "-subj", "/CN=localhost")
		(directory / "server.ext").write_text(
			"subjectAltName=DNS:localhost,IP:127.0.0.1\nextendedKeyUsage=serverAuth\n", encoding="ascii",
		)
		openssl("x509", "-req", "-in", directory / "server.csr", "-CA", directory / "ca.pem",
			"-CAkey", directory / "ca.key", "-CAcreateserial", "-out", directory / "server.pem",
			"-days", "2", "-extfile", directory / "server.ext")

	def trusted_context(self) -> ssl.SSLContext:
		return ssl.create_default_context(cafile=str(self.directory / "ca.pem"))

	def headers(self) -> dict[str, str]:
		return {"Authorization": f"Bearer {self.token}"}

	def start_session(self) -> httpx.Response:
		return self.client.post("/api/v1/sessions", headers=self.headers(), json={})

	def stop_session(self, session_id: str) -> httpx.Response:
		return self.client.delete(f"/api/v1/sessions/{session_id}", headers=self.headers())

	def websocket(self) -> SyncWebSocket:
		return SyncWebSocket(
			f"wss://127.0.0.1:{self.port}/api/v1/stream", ssl=self.trusted_context(),
			open_timeout=60, additional_headers=self.headers(),
		)

	def run(self, coroutine: Coroutine[Any, Any, Any], timeout: float = 60) -> Any:
		"""サーバーのイベントループ上でcoroutineを実行して結果を返す。"""
		return asyncio.run_coroutine_threadsafe(coroutine, self.loop).result(timeout=timeout)

	def close(self) -> None:
		self.client.close()
		self.server.should_exit = True
		self._thread.join(timeout=15)
		self._environment.stop()
		self._temporary.cleanup()
