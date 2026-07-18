from __future__ import annotations

from typing import Protocol

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .web_capture_security import origin_allowed


class Status(Protocol):
    def as_dict(self) -> dict[str, object]: ...


class ControlService(Protocol):
    def start(self) -> Status: ...

    def stop(self) -> Status: ...

    def reselect(self) -> Status: ...

    def status(self) -> Status: ...


def install_control_routes(app: FastAPI, service: ControlService) -> None:
    # 循環importを避けつつ、サービス固有例外だけを409へ変換する。
    from .web_app_service import WebAppConflictError

    async def execute(request: Request, operation) -> JSONResponse:
        if not origin_allowed(request.headers.get("origin")):
            return JSONResponse({}, status_code=403)
        try:
            status = await run_in_threadpool(operation)
        except WebAppConflictError as error:
            return JSONResponse({"detail": str(error)}, status_code=409)
        except Exception:
            return JSONResponse(service.status().as_dict(), status_code=500)
        return JSONResponse(status.as_dict())

    @app.post("/api/control/start")
    async def start(request: Request) -> JSONResponse:
        return await execute(request, service.start)

    @app.post("/api/control/stop")
    async def stop(request: Request) -> JSONResponse:
        return await execute(request, service.stop)

    @app.post("/api/control/reselect")
    async def reselect(request: Request) -> JSONResponse:
        return await execute(request, service.reselect)

    @app.get("/api/status")
    async def status() -> JSONResponse:
        body = service.status().as_dict()
        # トークン値は開始・再選択の応答だけに含め、状態確認では有効性のみ公開する。
        body.pop("session_token", None)
        return JSONResponse(body)
