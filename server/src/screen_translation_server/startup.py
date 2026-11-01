"""製品サーバーの起動時構成。環境変数からモデル準備(EngineLifecycle)を組み立てる。"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path

from screen_translation_server.engines.lifecycle import EngineLifecycle, ModelManifest
from screen_translation_server.engines.stanza_resources import StanzaManifest, StanzaResources, argos_stanza_directory

MANIFEST_VARIABLE = "SCREEN_TRANSLATION_MODEL_MANIFEST"
MODEL_DIR_VARIABLE = "SCREEN_TRANSLATION_MODEL_DIR"
STANZA_MANIFEST_VARIABLE = "SCREEN_TRANSLATION_STANZA_MANIFEST"


class StartupConfigurationError(ValueError):
	"""起動に必要なモデル設定の不足・不正。メッセージにパスや内容は含めない。"""


def manifest_from_environment(environment: Mapping[str, str] | None = None) -> tuple[ModelManifest, Path]:
	"""manifest(JSON)とモデル導入先を環境変数から読む。起動(lifecycle)と導入(provision)で共有する。"""
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
	return manifest, Path(model_dir)


def stanza_resources_from_environment(environment: Mapping[str, str] | None = None) -> StanzaResources:
	"""Stanza資源のmanifest(JSON)を環境変数から読む。起動(検証)と導入(provision)で共有する。"""
	env = os.environ if environment is None else environment
	stanza_path = env.get(STANZA_MANIFEST_VARIABLE)
	if not stanza_path:
		raise StartupConfigurationError(f"{STANZA_MANIFEST_VARIABLE} を設定してください。")
	return load_stanza_resources(stanza_path)


def load_stanza_resources(stanza_path: str | Path) -> StanzaResources:
	try:
		stanza_manifest = StanzaManifest.from_json(json.loads(Path(stanza_path).read_text(encoding="utf-8")))
		stanza_manifest.validate()
	except (OSError, ValueError, TypeError) as error:
		raise StartupConfigurationError(f"Stanza資源manifestを読み込めません ({type(error).__name__})。") from None
	return StanzaResources(stanza_manifest, argos_stanza_directory)


def lifecycle_from_environment(environment: Mapping[str, str] | None = None) -> EngineLifecycle:
	"""モデル・Stanza資源のmanifest(JSON)とモデル導入先を環境変数から読み、EngineLifecycleを作る。"""
	manifest, model_dir = manifest_from_environment(environment)
	return EngineLifecycle(manifest, model_dir, stanza_resources=stanza_resources_from_environment(environment))
