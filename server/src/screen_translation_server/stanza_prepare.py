"""Stanza資源を準備する管理者向け手順(`python -m screen_translation_server.stanza_prepare <manifest>`)。

Argosの英日パッケージ導入後に実行する。外向き通信が必要なのはこの準備だけで、サーバーの実行時は
通信しない。取得した資源はmanifestのサイズ・SHA-256で検証し、永続領域(Argosのデータ領域)へ置く。
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path

from screen_translation_server.engines.stanza_resources import (
	StanzaManifest,
	StanzaResourceError,
	StanzaResources,
	argos_stanza_directory,
)


def prepare(manifest_path: str | Path) -> None:
	"""manifestを読み、足りない・壊れた資源を取得して検証する。失敗は例外で返す。"""
	try:
		manifest = StanzaManifest.from_json(json.loads(Path(manifest_path).read_text(encoding="utf-8")))
		manifest.validate()
	except (OSError, ValueError, TypeError) as error:
		raise StanzaResourceError(f"Stanza資源manifestを読み込めません ({type(error).__name__})。") from None
	resources = StanzaResources(manifest, argos_stanza_directory)
	resources.provision()
	resources.verify()


def main(argv: Sequence[str] | None = None) -> int:
	args = list(sys.argv[1:] if argv is None else argv)
	if len(args) != 1:
		print("使い方: python -m screen_translation_server.stanza_prepare <Stanza資源manifest.json>", file=sys.stderr)
		return 2
	try:
		prepare(args[0])
	except StanzaResourceError as error:
		print(f"Stanza資源の準備に失敗しました: {error}", file=sys.stderr)
		return 1
	print("Stanza資源の準備が完了しました。", flush=True)
	return 0


if __name__ == "__main__":
	sys.exit(main())
