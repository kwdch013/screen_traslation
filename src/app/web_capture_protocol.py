from __future__ import annotations

import asyncio

from uvicorn.protocols.http.h11_impl import H11Protocol


def create_header_timeout_protocol(timeout_seconds: float) -> type[H11Protocol]:
    """初回リクエストのヘッダ受信期限を持つh11プロトコルを生成する。"""

    class HeaderTimeoutH11Protocol(H11Protocol):
        _header_timeout_handle: asyncio.TimerHandle | None = None

        def connection_made(self, transport: asyncio.Transport) -> None:
            super().connection_made(transport)
            # keep-alive期限はリクエスト間にしか効かないため、接続受理時から別の絶対期限を張る。
            # データ受信では延長せず、h11が全ヘッダをRequestへ変換した時だけ解除する。
            self._header_timeout_handle = self.loop.call_later(
                timeout_seconds,
                self._close_incomplete_headers,
            )

        def data_received(self, data: bytes) -> None:
            super().data_received(data)
            if self.scope is not None:
                self._cancel_header_timeout()

        def connection_lost(self, exc: Exception | None) -> None:
            self._cancel_header_timeout()
            super().connection_lost(exc)

        def _close_incomplete_headers(self) -> None:
            self._header_timeout_handle = None
            if self.scope is None:
                self.transport.close()

        def _cancel_header_timeout(self) -> None:
            if self._header_timeout_handle is not None:
                self._header_timeout_handle.cancel()
                self._header_timeout_handle = None

    return HeaderTimeoutH11Protocol
