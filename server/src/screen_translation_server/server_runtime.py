"""SIGHUPでTLS証明書を再読込するUvicorn Server (Issue #249でapp.pyから分離)。"""

from __future__ import annotations

from contextlib import contextmanager
import logging
import signal
import ssl
import threading
from types import FrameType
from typing import Iterator

import uvicorn

_LOGGER = logging.getLogger(__name__)


class ReloadableServer(uvicorn.Server):
	"""SIGHUPで同じlistenerのTLS証明書を再読込する。"""

	def __init__(
		self,
		config: uvicorn.Config,
		tls_context: ssl.SSLContext,
		certificate_path: str | None,
		private_key_path: str | None,
	) -> None:
		super().__init__(config)
		self._tls_context = tls_context
		self._certificate_path = certificate_path
		self._private_key_path = private_key_path

	@contextmanager
	def capture_signals(self) -> Iterator[None]:
		reload_signal = getattr(signal, "SIGHUP", None)
		with super().capture_signals():
			if reload_signal is None or threading.current_thread() is not threading.main_thread():
				yield
				return
			original_handler = signal.signal(reload_signal, self.handle_exit)
			try:
				yield
			finally:
				signal.signal(reload_signal, original_handler)

	def handle_exit(self, sig: int, frame: FrameType | None) -> None:
		if sig == getattr(signal, "SIGHUP", None):
			if not self._certificate_path or not self._private_key_path:
				_LOGGER.error("TLS証明書再読込を拒否しました。設定が不足しています。")
				self.should_exit = True
				return
			try:
				self._tls_context.load_cert_chain(self._certificate_path, self._private_key_path)
			except (OSError, ssl.SSLError):
				_LOGGER.error("TLS証明書再読込に失敗したため、安全に停止します。")
				self.should_exit = True
				return
			_LOGGER.info("TLS証明書を再読込しました。")
			return
		super().handle_exit(sig, frame)
