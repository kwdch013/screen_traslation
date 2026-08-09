from __future__ import annotations

import secrets
from pathlib import Path
from typing import Protocol

from fastapi import FastAPI, Request, Response
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import RequestResponseEndpoint

from .web_capture_security import (
    MAX_FRAME_BYTES,
    TOKEN_HEADER,
    FrameBodyTooLargeError,
    FrameReadTimeoutError,
    content_type_value,
    decode_frame_bytes,
    host_allowed,
    origin_allowed,
    read_request_body,
)
from .web_frontend import DEFAULT_FRONTEND_DIST, install_frontend_route


class CaptureSession(Protocol):
    @property
    def session_token(self) -> str: ...

    def accept_frame(self, token: str, image: object) -> bool: ...


def create_capture_app(
    server: CaptureSession,
    frontend_dist: Path = DEFAULT_FRONTEND_DIST,
) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def protect_host_and_response(request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not host_allowed(request.headers.get("host")):
            return _status_response(403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.post("/frame")
    async def receive_frame(request: Request) -> Response:
        if not origin_allowed(request.headers.get("origin")):
            return _status_response(403)
        content_type = content_type_value(request.headers.get("content-type"))
        if content_type is None:
            return _status_response(415)
        content_length_status, content_length = _parse_content_length(request.headers.get("content-length"))
        if content_length_status is not None:
            return _status_response(content_length_status)
        token = request.headers.get(TOKEN_HEADER, "")
        # 巨大・低速な本文を読む前に失効済みセッションを早期拒否する。
        if not token or not secrets.compare_digest(token, server.session_token):
            return _status_response(403)
        try:
            payload = await read_request_body(request)
        except FrameBodyTooLargeError:
            return _status_response(413)
        except FrameReadTimeoutError:
            return _status_response(408)
        if len(payload) > MAX_FRAME_BYTES:
            return _status_response(413)
        if len(payload) != content_length:
            return _status_response(400)
        try:
            image = await run_in_threadpool(decode_frame_bytes, payload, content_type)
        except Exception:
            return _status_response(400)
        # デコード中のセッション更新を考慮し、保存直前にロック下で再検証する。
        if not server.accept_frame(token, image):
            return _status_response(403)
        return _status_response(204)

    install_frontend_route(app, frontend_dist)
    return app


def _parse_content_length(raw_length: str | None) -> tuple[int | None, int]:
    if raw_length is None:
        return 411, 0
    try:
        length = int(raw_length)
    except ValueError:
        return 400, 0
    if length <= 0:
        return 400, 0
    if length > MAX_FRAME_BYTES:
        return 413, 0
    return None, length


def _status_response(status_code: int) -> Response:
    return Response(
        status_code=status_code,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
