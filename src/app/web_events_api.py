from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
import json
from queue import Empty
from time import monotonic

from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse

from .result_events import SseEvent, TranslationEventPublisher
from .web_capture_security import origin_allowed


HEARTBEAT_SECONDS = 15.0


def install_event_routes(app: FastAPI, publisher: TranslationEventPublisher) -> None:
    @app.get("/api/events")
    async def events(request: Request) -> Response:
        if not origin_allowed(request.headers.get("origin")):
            return Response(status_code=403)
        return StreamingResponse(
            event_stream(publisher),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )


async def event_stream(
    publisher: TranslationEventPublisher,
    heartbeat_seconds: float = HEARTBEAT_SECONDS,
) -> AsyncGenerator[str]:
    subscription = publisher.subscribe()
    heartbeat_at = monotonic() + heartbeat_seconds
    try:
        while True:
            try:
                event = subscription.get_nowait()
            except Empty:
                remaining = heartbeat_at - monotonic()
                if remaining <= 0:
                    yield ": heartbeat\n\n"
                    heartbeat_at = monotonic() + heartbeat_seconds
                    continue
                # 同期Queueでパイプライン側を待たせず、イベントループも占有しない。
                await asyncio.sleep(min(remaining, 0.05))
                continue
            heartbeat_at = monotonic() + heartbeat_seconds
            yield format_sse_event(event)
    finally:
        subscription.close()


def format_sse_event(event: SseEvent) -> str:
    data = json.dumps(event.data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event.event}\ndata: {data}\n\n"
