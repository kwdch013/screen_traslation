"""本番のモデル導入コマンド。`python -m screen_translation_server.provision`。

外向き通信が必要なのは、この準備段階だけ。実行時のサーバーはモデルを取得しない。
manifest(固定のURL・サイズ・SHA-256・ライセンス同意)と導入先は、起動と同じ環境変数から読む。
取得済みなら再ダウンロードせず、検証と再導入だけを行う。
Stanzaの文分割資源の準備はIssue #189の担当で、ここでは扱わない。
"""

from __future__ import annotations

import sys
from collections.abc import Mapping

from screen_translation_server.engines.lifecycle import ModelProvisioner
from screen_translation_server.startup import StartupConfigurationError, manifest_from_environment


def main(environment: Mapping[str, str] | None = None) -> int:
	try:
		manifest, model_dir = manifest_from_environment(environment)
	except StartupConfigurationError as error:
		print(error, file=sys.stderr)
		return 2
	provisioner = ModelProvisioner(manifest, model_dir, progress=lambda stage: print(f"モデル準備: {stage}", flush=True))
	try:
		provisioner.provision()
	except Exception:
		# 例外の詳細にはパスや取得先が含まれ得るため、検証済みの安全な理由だけを出す。
		print(f"モデル準備に失敗しました: {provisioner.failure_reason}", file=sys.stderr)
		return 1
	print("モデル準備完了", flush=True)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
