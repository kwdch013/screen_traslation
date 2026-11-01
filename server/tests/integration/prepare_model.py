"""結合試験用のArgos英日モデルを名前付きボリュームへ取得・導入し、初回資源を温める。

外部通信が必要なため、通常の結合試験(network_mode: none)とは別のComposeサービスで実行する。
取得したファイルは`ModelProvisioner`が固定manifestのサイズ・SHA-256で検証する。
取得済みなら再ダウンロードせず検証と再導入だけを行う。導入先は環境変数XDG_DATA_HOMEで
ボリューム内へ向ける。Argosの文分割(Stanza)の資源は、製品と同じ準備手順
(`screen_translation_server.provision`と同じ`StanzaResources.provision`)で固定manifestのサイズ・SHA-256を検証して置く。
実行時は外部取得を行わないため(#189)、準備後の翻訳を試験側で温める必要はない。
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

from screen_translation_server.engines.lifecycle import ModelManifest, ModelProvisioner

MANIFEST_PATH = Path(__file__).resolve().parents[1] / "fixtures/pipeline/model-manifest.json"
# 本番と同じmanifestを使う(コンテナでは/workspace/deploy、リポジトリではserver/deploy)。
STANZA_MANIFEST_PATH = Path(__file__).resolve().parents[2] / "deploy/stanza-manifest.json"


def load_manifest() -> ModelManifest:
	return ModelManifest(**json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))


def main(destination: str) -> int:
	provisioner = ModelProvisioner(
		load_manifest(), Path(destination),
		progress=lambda stage: print(f"モデル準備: {stage}", flush=True),
	)
	path = provisioner.provision()
	from screen_translation_server.startup import load_stanza_resources

	resources = load_stanza_resources(STANZA_MANIFEST_PATH)
	resources.provision()
	resources.verify()
	print("Stanza資源の準備完了", flush=True)
	print(f"モデル準備完了: {path.name}", flush=True)
	return 0


if __name__ == "__main__":
	sys.exit(main(sys.argv[1]))
