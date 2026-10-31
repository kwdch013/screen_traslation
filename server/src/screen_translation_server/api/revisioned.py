"""設定・辞書APIで共有する認可・本文検証・revision条件付き更新の流れ。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import json
import logging
import re
from typing import Any
from uuid import uuid4

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from screen_translation_server.api.input_limits import (
	HTTP_JSON_MAX_BYTES,
	InputLimitError,
	read_limited_body,
)
from screen_translation_server.security.auth import Role
from screen_translation_server.storage import RevisionConflict, StoreValidationError

_IF_MATCH = re.compile(r'^"([1-9][0-9]{0,19})"$')
_LOGGER = logging.getLogger(__name__)
_READ_ROLES = frozenset({Role.DEVICE, Role.ADMIN})
EFFECTIVE_FROM_HEADER = "X-Effective-From"
EFFECTIVE_FROM_VALUE = "next-frame"


def error_response(code: str, message: str, status: int, headers: dict[str, str] | None = None) -> JSONResponse:
	body = {"code": code, "message": message, "correlation_id": str(uuid4()), "retryable": False}
	return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store", **(headers or {})})


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
	result: dict[str, Any] = {}
	for key, value in pairs:
		if key in result:
			raise ValueError("重複key")
		result[key] = value
	return result


def _etag(revision: object) -> str:
	return f'"{revision}"'


def build_routes(
	app: Starlette,
	*,
	path: str,
	get_store: Callable[[], Any | None],
	apply_committed: Callable[[dict[str, Any]], None],
) -> list[Route]:
	"""GET/PUTのrouteを作る。保存成功後の反映は同期callbackで行い、awaitを挟まない。"""
	update_lock = asyncio.Lock()

	def ok(value: dict[str, Any], *, updated: bool) -> JSONResponse:
		headers = {"ETag": _etag(value["revision"]), "Cache-Control": "no-store"}
		if updated:
			headers[EFFECTIVE_FROM_HEADER] = EFFECTIVE_FROM_VALUE
		return JSONResponse(value, headers=headers)

	def internal() -> JSONResponse:
		return error_response("INTERNAL_ERROR", "処理に失敗しました。", 500)

	async def read(request: Request) -> Response:
		result = await app.state.authenticate(request, _READ_ROLES)
		if isinstance(result, Response):
			return result
		store = get_store()
		if store is None:
			return internal()
		try:
			current = await asyncio.to_thread(store.get)
		except Exception:
			# 例外文字列にはパスが含まれうるため、固定文言だけを記録する。
			_LOGGER.error("revisioned_read_failed")
			return internal()
		return ok(current, updated=False)

	async def write(request: Request) -> Response:
		result = await app.state.authenticate(request, _READ_ROLES)
		if isinstance(result, Response):
			return result
		if result.role is not Role.ADMIN:
			return error_response("FORBIDDEN", "この操作は許可されていません。", 403)
		too_large = error_response("PAYLOAD_TOO_LARGE", "画像または要求サイズが上限を超えています。", 413)
		try:
			declared = request.headers.get("content-length")
			if declared is not None and not 0 <= int(declared) <= HTTP_JSON_MAX_BYTES:
				return too_large
			body = await read_limited_body(
				request.stream(), maximum=HTTP_JSON_MAX_BYTES, timeout_seconds=app.state.http_body_timeout,
			)
		except (InputLimitError, ValueError):
			return too_large
		invalid = error_response("INVALID_REQUEST", "設定または辞書の内容が不正です。", 422)
		media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
		match = _IF_MATCH.match(request.headers.get("if-match", ""))
		if media_type != "application/json" or match is None:
			return invalid
		try:
			payload = json.loads(body.decode("utf-8"), object_pairs_hook=_unique_object)
		except ValueError:
			return invalid
		store = get_store()
		if store is None:
			return internal()
		async with update_lock:
			try:
				updated = await asyncio.to_thread(store.update, int(match.group(1)), payload)
			except RevisionConflict as conflict:
				return error_response("REVISION_CONFLICT", "設定が更新されています。再読み込みしてください。",
					409, {"ETag": _etag(conflict.current_revision)})
			except StoreValidationError as error:
				return too_large if error.too_large else invalid
			except Exception:
				_LOGGER.error("revisioned_update_failed")
				return internal()
			# 保存確定と同じtickで反映し、以降の新規frameだけが新値を使う。
			apply_committed(updated)
		return ok(updated, updated=True)

	return [Route(path, read, methods=["GET"]), Route(path, write, methods=["PUT"])]
