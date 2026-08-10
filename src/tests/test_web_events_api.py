from __future__ import annotations

import unittest

from starlette.requests import Request
from starlette.routing import Route
from typing import cast

from app.contracts import Rect, TranslationRegion, TranslationResult
from app.result_events import TranslationEventPublisher
from app.web_capture import WebCaptureServer
from app.web_events_api import event_stream, format_sse_event, install_event_routes


class WebEventsApiTest(unittest.IsolatedAsyncioTestCase):
    async def test_event_stream_yields_state_result_and_heartbeat(self) -> None:
        publisher = TranslationEventPublisher()
        publisher.publish_state(generation=1, state="running", error_message=None)
        stream = event_stream(publisher, heartbeat_seconds=0.001)
        try:
            state = await anext(stream)
            publisher.publish(
                TranslationResult(
                    generation=1,
                    frame_id=4,
                    captured_at=1.0,
                    processed_at=2.0,
                    frame_width=640,
                    frame_height=360,
                    regions=(
                        TranslationRegion(
                            source="New Game",
                            translated="ニューゲーム",
                            bounds=Rect(10, 20, 120, 30),
                            positioning="available",
                        ),
                        TranslationRegion(
                            source="Continue",
                            translated="続ける",
                            bounds=Rect(160, 70, 90, 24),
                            positioning="available",
                        ),
                    ),
                )
            )
            result = await anext(stream)
            heartbeat = await anext(stream)
        finally:
            await stream.aclose()

        self.assertIn("event: state", state)
        self.assertIn('"frame_id":4', result)
        self.assertEqual(result.count('"positioning":"available"'), 2)
        self.assertIn('"x":160,"y":70,"width":90,"height":24', result)
        self.assertEqual(heartbeat, ": heartbeat\n\n")

    async def test_format_sse_event_serializes_json_without_ascii_escaping(
        self,
    ) -> None:
        publisher = TranslationEventPublisher()
        publisher.publish_state(generation=0, state="error", error_message="翻訳失敗")
        subscription = publisher.subscribe()
        self.addCleanup(subscription.close)

        formatted = format_sse_event(subscription.get_nowait())

        self.assertIn("翻訳失敗", formatted)
        self.assertTrue(formatted.endswith("\n\n"))

    async def test_events_rejects_foreign_origin(self) -> None:
        server = WebCaptureServer()
        install_event_routes(server.app, TranslationEventPublisher())
        route = cast(
            Route,
            next(
                route
                for route in server.app.routes
                if getattr(route, "path", None) == "/api/events"
            ),
        )
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/events",
                "headers": [(b"origin", b"https://evil.example.com")],
            }
        )

        response = await route.endpoint(request)

        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
