"""結合試験用のArgos英日モデルを名前付きボリュームへ取得・導入し、初回資源を温める。

外部通信が必要なため、通常の結合試験(network_mode: none)とは別のComposeサービスで実行する。
取得したファイルは`ModelProvisioner`が固定manifestのサイズ・SHA-256で検証する。
取得済みなら再ダウンロードせず検証と再導入だけを行う。導入先は環境変数XDG_DATA_HOMEで
ボリューム内へ向ける。ArgosはSentence分割のStanza資源を初回翻訳時に外部から取得するため、
ここで1度翻訳して資源をボリュームへ保存し、オフラインの結合試験で再利用させる。
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

from screen_translation_server.engines.lifecycle import ModelManifest, ModelProvisioner

MANIFEST_PATH = Path(__file__).resolve().parents[1] / "fixtures/pipeline/model-manifest.json"


def load_manifest() -> ModelManifest:
	return ModelManifest(**json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))


def main(destination: str) -> int:
	provisioner = ModelProvisioner(
		load_manifest(), Path(destination),
		progress=lambda stage: print(f"モデル準備: {stage}", flush=True),
	)
	path = provisioner.provision()
	from screen_translation_server.engines import ArgosTranslator

	ArgosTranslator("en", "ja").translate("Hello.")
	print("初回資源の取得完了", flush=True)
	print(f"モデル準備完了: {path.name}", flush=True)
	return 0


if __name__ == "__main__":
	sys.exit(main(sys.argv[1]))
