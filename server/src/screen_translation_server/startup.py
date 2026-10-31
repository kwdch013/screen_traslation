"""製品サーバーの起動時構成。環境変数からモデル準備(EngineLifecycle)を組み立てる。"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path

from screen_translation_server.engines.lifecycle import EngineLifecycle, ModelManifest

MANIFEST_VARIABLE = "SCREEN_TRANSLATION_MODEL_MANIFEST"
MODEL_DIR_VARIABLE = "SCREEN_TRANSLATION_MODEL_DIR"


class StartupConfigurationError(ValueError):
	"""起動に必要なモデル設定の不足・不正。メッセージにパスや内容は含めない。"""


def lifecycle_from_environment(environment: Mapping[str, str] | None = None) -> EngineLifecycle:
	"""manifest(JSON)とモデル導入先を環境変数から読み、EngineLifecycleを作る。"""
	env = os.environ if environment is None else environment
	manifest_path = env.get(MANIFEST_VARIABLE)
	model_dir = env.get(MODEL_DIR_VARIABLE)
	if not manifest_path or not model_dir:
		raise StartupConfigurationError(f"{MANIFEST_VARIABLE} と {MODEL_DIR_VARIABLE} を設定してください。")
	try:
		manifest = ModelManifest(**json.loads(Path(manifest_path).read_text(encoding="utf-8")))
		manifest.validate()
	except (OSError, ValueError, TypeError) as error:
		# 原因の詳細(パス・内容)は出さず、型名だけで運用者に気づかせる。
		raise StartupConfigurationError(f"モデルmanifestを読み込めません ({type(error).__name__})。") from None
	return EngineLifecycle(manifest, model_dir)
