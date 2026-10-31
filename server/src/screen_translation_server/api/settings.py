"""設定API(GET/PUT /api/v1/settings)。保存済み値を実行中のpipelineへ反映する。"""

from __future__ import annotations

from typing import Any

from starlette.applications import Starlette
from starlette.routing import Route

from screen_translation_server.api.revisioned import build_routes


def settings_routes(app: Starlette) -> list[Route]:
	def apply_committed(updated: dict[str, Any]) -> None:
		app.state.capture_fps = updated["capture_fps"]
		pipeline = app.state.pipeline
		if pipeline is not None and hasattr(pipeline, "set_capture_fps"):
			pipeline.set_capture_fps(updated["capture_fps"])

	return build_routes(
		app, path="/api/v1/settings",
		get_store=lambda: app.state.settings_store, apply_committed=apply_committed,
	)
