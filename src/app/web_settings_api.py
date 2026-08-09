from __future__ import annotations

from typing import Protocol

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .glossary import GlossaryTermExistsError, GlossaryTermNotFoundError
from .web_capture_security import origin_allowed


class SettingsService(Protocol):
    def public_config(self) -> dict[str, object]: ...

    def update_config(self, changes: dict[str, object]) -> dict[str, object]: ...

    def glossary_terms(self) -> list[dict[str, str]]: ...

    def register_glossary_term(self, source: str, target: str) -> dict[str, str]: ...

    def delete_glossary_term(self, source: str) -> None: ...


def install_settings_routes(app: FastAPI, service: SettingsService) -> None:
    @app.get("/api/config")
    async def get_config() -> JSONResponse:
        return JSONResponse(service.public_config())

    @app.put("/api/config")
    async def put_config(request: Request) -> JSONResponse:
        if not origin_allowed(request.headers.get("origin")):
            return JSONResponse({}, status_code=403)
        try:
            changes = await _json_object(request)
            body = await run_in_threadpool(service.update_config, changes)
        except ValueError as error:
            return JSONResponse({"detail": str(error)}, status_code=400)
        return JSONResponse(body)

    @app.get("/api/glossary")
    async def get_glossary() -> JSONResponse:
        return JSONResponse(service.glossary_terms())

    @app.post("/api/glossary")
    async def post_glossary(request: Request) -> JSONResponse:
        if not origin_allowed(request.headers.get("origin")):
            return JSONResponse({}, status_code=403)
        try:
            payload = await _json_object(request)
            source, target = _glossary_values(payload)
            body = await run_in_threadpool(service.register_glossary_term, source, target)
        except GlossaryTermExistsError as error:
            return JSONResponse({"detail": str(error)}, status_code=409)
        except ValueError as error:
            return JSONResponse({"detail": str(error)}, status_code=400)
        return JSONResponse(body, status_code=201)

    @app.delete("/api/glossary/{source:path}")
    async def delete_glossary(source: str, request: Request) -> Response:
        if not origin_allowed(request.headers.get("origin")):
            return JSONResponse({}, status_code=403)
        try:
            await run_in_threadpool(service.delete_glossary_term, source)
        except GlossaryTermNotFoundError:
            return JSONResponse({"detail": f"用語が見つかりません: {source}"}, status_code=404)
        return Response(status_code=204)


async def _json_object(request: Request) -> dict[str, object]:
    try:
        payload = await request.json()
    except Exception as error:
        raise ValueError("JSONオブジェクトを指定してください。") from error
    if not isinstance(payload, dict):
        raise ValueError("JSONオブジェクトを指定してください。")
    return payload


def _glossary_values(payload: dict[str, object]) -> tuple[str, str]:
    if set(payload) != {"source", "target"}:
        raise ValueError("sourceとtargetを指定してください。")
    source = payload["source"]
    target = payload["target"]
    if not isinstance(source, str) or not isinstance(target, str):
        raise ValueError("sourceとtargetは文字列で指定してください。")
    return source, target
