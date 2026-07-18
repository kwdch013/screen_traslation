from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, PlainTextResponse
from starlette.routing import Match, Route


DEFAULT_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
_RESERVED_PATHS = ("api", "frame")
_MISSING_BUILD_MESSAGE = (
    "フロントエンドのビルド成果物 frontend/dist が見つかりません。"
    "frontend ディレクトリで npm run build を実行してください。"
)


def install_frontend_route(app: FastAPI, frontend_dist: Path) -> None:
    async def serve_frontend(request: Request) -> Response:
        return _frontend_response(request, frontend_dist)

    app.router.routes.append(
        FrontendRoute("/{path:path}", serve_frontend, methods=["GET"], name="frontend"),
    )


class FrontendRoute(Route):
    """API予約パスを除外し、後から登録されたAPIルートへ処理を渡す。"""

    def matches(self, scope: dict[str, Any]) -> tuple[Match, dict[str, Any]]:
        if _is_reserved_path(scope.get("path", "")):
            return Match.NONE, {}
        return super().matches(scope)


def _frontend_response(request: Request, frontend_dist: Path) -> Response:
    index_path = _safe_static_path(frontend_dist, "/index.html")
    if index_path is None:
        return Response(status_code=404)
    if not index_path.is_file():
        return PlainTextResponse(_MISSING_BUILD_MESSAGE, status_code=503)
    if request.url.path == "/":
        return FileResponse(index_path, media_type="text/html")

    static_path = _safe_static_path(frontend_dist, request.url.path)
    if static_path is not None and static_path.is_file():
        return FileResponse(static_path)
    return Response(status_code=404)


def _is_reserved_path(path: str) -> bool:
    first_segment = path.lstrip("/").split("/", 1)[0]
    return first_segment in _RESERVED_PATHS


def _safe_static_path(frontend_dist: Path, request_path: str) -> Path | None:
    resolved_dist = frontend_dist.resolve()
    candidate = (resolved_dist / request_path.lstrip("/")).resolve()
    try:
        candidate.relative_to(resolved_dist)
    except ValueError:
        return None
    return candidate
