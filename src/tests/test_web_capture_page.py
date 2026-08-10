from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from starlette.requests import Request
from starlette.responses import FileResponse
from starlette.routing import Match, Route
from starlette.types import Scope
from typing import cast

from app.web_capture import WebCaptureServer


class WebCapturePageTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.dist = self.root / "dist"
        self.dist.mkdir()
        self.outside = self.root / "outside"
        self.outside.mkdir()
        (self.outside / "secret.txt").write_text("secret", encoding="utf-8")
        (self.dist / "assets").mkdir()
        (self.dist / "index.html").write_text(
            '<!doctype html><div id="root"></div><script src="/assets/app-abc123.js"></script>',
            encoding="utf-8",
        )
        (self.dist / "assets" / "app-abc123.js").write_text(
            "navigator.mediaDevices.getDisplayMedia({video: true});",
            encoding="utf-8",
        )
        (self.dist / "favicon.svg").write_text("<svg></svg>", encoding="utf-8")
        self.server = WebCaptureServer(frontend_dist=self.dist)
        self.frontend_route = cast(
            Route,
            next(
                route
                for route in self.server.app.routes
                if getattr(route, "name", None) == "frontend"
            ),
        )

    async def test_root_serves_built_react_index_without_session_token(self) -> None:
        response = await self.frontend_route.endpoint(_request("/"))

        self.assertIsInstance(response, FileResponse)
        self.assertEqual(Path(response.path), self.dist / "index.html")
        page = Path(response.path).read_text(encoding="utf-8")
        self.assertIn('<div id="root"></div>', page)
        self.assertNotIn(self.server.session_token, page)
        self.assertEqual(response.media_type, "text/html")

    async def test_hashed_asset_is_served(self) -> None:
        response = await self.frontend_route.endpoint(_request("/assets/app-abc123.js"))

        self.assertIsInstance(response, FileResponse)
        self.assertEqual(Path(response.path), self.dist / "assets" / "app-abc123.js")
        self.assertIn(
            "getDisplayMedia", Path(response.path).read_text(encoding="utf-8")
        )

    async def test_dist_root_file_is_served(self) -> None:
        response = await self.frontend_route.endpoint(_request("/favicon.svg"))

        self.assertIsInstance(response, FileResponse)
        self.assertEqual(Path(response.path), self.dist / "favicon.svg")

    async def test_unknown_path_returns_404(self) -> None:
        response = await self.frontend_route.endpoint(_request("/preview/history"))

        self.assertEqual(response.status_code, 404)

    async def test_parent_directory_traversal_returns_404(self) -> None:
        response = await self.frontend_route.endpoint(
            _request("/../outside/secret.txt")
        )

        self.assertEqual(response.status_code, 404)

    async def test_url_encoded_parent_directory_traversal_returns_404(self) -> None:
        response = await self.frontend_route.endpoint(
            _request("/../outside/secret.txt", raw_path=b"/%2e%2e/outside/secret.txt"),
        )

        self.assertEqual(response.status_code, 404)

    async def test_external_index_symlink_returns_404(self) -> None:
        (self.dist / "index.html").unlink()
        (self.dist / "index.html").symlink_to(self.outside / "secret.txt")

        response = await self.frontend_route.endpoint(_request("/"))

        self.assertEqual(response.status_code, 404)

    async def test_api_path_is_not_swallowed_by_frontend_route(self) -> None:
        match, _ = self.frontend_route.matches(_scope("/api/not-found"))

        self.assertIs(match, Match.NONE)

    async def test_frame_path_is_not_swallowed_by_frontend_route(self) -> None:
        match, _ = self.frontend_route.matches(_scope("/frame"))

        self.assertIs(match, Match.NONE)
        frame_matches = [
            route.matches(_scope("/frame"))[0]
            for route in self.server.app.routes
            if getattr(route, "path", None) == "/frame"
        ]
        self.assertIn(Match.PARTIAL, frame_matches)

    async def test_missing_build_returns_clear_error(self) -> None:
        missing_server = WebCaptureServer(frontend_dist=self.dist / "missing")
        route = cast(
            Route,
            next(
                candidate
                for candidate in missing_server.app.routes
                if getattr(candidate, "name", None) == "frontend"
            ),
        )

        response = await route.endpoint(_request("/"))

        self.assertEqual(response.status_code, 503)
        self.assertIn("npm run build", response.body.decode("utf-8"))
        self.assertIn("frontend/dist", response.body.decode("utf-8"))


def _request(path: str, raw_path: bytes | None = None) -> Request:
    return Request(_scope(path, raw_path))


def _scope(path: str, raw_path: bytes | None = None) -> Scope:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": raw_path or path.encode("ascii"),
        "query_string": b"",
        "headers": [(b"host", b"127.0.0.1:8765")],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8765),
        "root_path": "",
    }


if __name__ == "__main__":
    unittest.main()
