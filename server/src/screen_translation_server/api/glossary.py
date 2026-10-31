"""辞書API(GET/PUT /api/v1/glossary)。更新時にsession revisionと翻訳キャッシュを同時に切り替える。"""

from __future__ import annotations

from typing import Any

from starlette.applications import Starlette
from starlette.routing import Route

from screen_translation_server.api.revisioned import build_routes


def glossary_routes(app: Starlette) -> list[Route]:
	def apply_committed(updated: dict[str, Any]) -> None:
		# 辞書とキャッシュを先に差し替え、その後にsession revisionを進める。
		# 旧revisionのframeはこの後のis_frame_current照合で配信前に破棄される。
		app.state.glossary_runtime.apply(updated["entries"], updated["revision"])
		app.state.sessions.set_dictionary_revision(updated["revision"])

	return build_routes(
		app, path="/api/v1/glossary",
		get_store=lambda: app.state.glossary_store, apply_committed=apply_committed,
	)
