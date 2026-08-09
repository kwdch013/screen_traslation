from __future__ import annotations

import asyncio

from uvicorn.protocols.http.h11_impl import H11Protocol

# uvicorn 0.35以上0.52未満の非公開H11Protocol APIに依存する。
# loop・scope・transportとon_response_complete()の挙動を前提とするため、
# uvicorn更新時はこのファイルの互換性検査と実サーバーテストをガードとして確認する。


def create_header_timeout_protocol(timeout_seconds: float) -> type[H11Protocol]:
    """各リクエストのヘッダ受信期限を持つh11プロトコルを生成する。"""

    class HeaderTimeoutH11Protocol(H11Protocol):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)  # type: ignore[arg-type]
            self._verify_uvicorn_internal_api()
            self._header_timeout_handle: asyncio.TimerHandle | None = None
            self._request_generation = 0

        def connection_made(self, transport: asyncio.Transport) -> None:
            super().connection_made(transport)
            # keep-alive期限はリクエスト間にしか効かないため、接続受理時から別の絶対期限を張る。
            self._arm_header_timeout()

        def data_received(self, data: bytes) -> None:
            previous_scope = self.scope
            super().data_received(data)
            self._record_completed_request(previous_scope)

        def on_response_complete(self) -> None:
            completed_scope = self.scope
            super().on_response_complete()
            if self.transport.is_closing():
                self._cancel_header_timeout()
            elif self.scope is completed_scope:
                # 応答完了後もscopeは残るため、同一性を期限対象の世代として保持する。
                self._arm_header_timeout()
            else:
                # super()内でパイプライン済みの次Requestが同期的に完成する場合がある。
                self._record_completed_request(completed_scope)

        def connection_lost(self, exc: Exception | None) -> None:
            self._cancel_header_timeout()
            super().connection_lost(exc)

        def _arm_header_timeout(self) -> None:
            self._cancel_header_timeout()
            generation = self._request_generation
            scope = self.scope
            self._header_timeout_handle = self.loop.call_later(
                timeout_seconds,
                self._close_incomplete_headers,
                generation,
                scope,
            )

        def _close_incomplete_headers(self, generation: int, scope: object) -> None:
            self._header_timeout_handle = None
            if generation == self._request_generation and self.scope is scope:
                self.transport.close()

        def _record_completed_request(self, previous_scope: object) -> None:
            if self.scope is previous_scope:
                return
            self._request_generation += 1
            self._cancel_header_timeout()

        def _cancel_header_timeout(self) -> None:
            if self._header_timeout_handle is not None:
                self._header_timeout_handle.cancel()
                self._header_timeout_handle = None

        def _verify_uvicorn_internal_api(self) -> None:
            required_attributes = ("loop", "scope", "transport")
            missing = [name for name in required_attributes if not hasattr(self, name)]
            if missing or self.scope is not None or not callable(getattr(self.loop, "call_later", None)):
                details = ", ".join(missing) if missing else "初期状態またはイベントループ"
                raise RuntimeError(f"uvicornの内部APIが想定と異なります: {details}")

    return HeaderTimeoutH11Protocol
