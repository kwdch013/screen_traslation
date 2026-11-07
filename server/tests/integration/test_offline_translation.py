"""外向き通信なしで、準備済みのStanza資源だけを使って翻訳できることを確認する(#189)。

統合試験コンテナは`network_mode: none`のため外部へ出られないが、それだけに頼らず、
接続の試行そのものを失敗させて「取得を試みていない」ことも直接確認する。
"""

from __future__ import annotations

import shutil
import socket
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from pipeline_support import JAPANESE, model_directory, require_model, stanza_resources
from screen_translation_server.engines.lifecycle import EngineLifecycle, ModelState
from screen_translation_server.engines.lifecycle import _load_engines
from screen_translation_server.engines.stanza_resources import StanzaResources, argos_stanza_directory


class NoNetwork(AssertionError):
	pass


def forbid_connect(*_args: Any, **_kwargs: Any) -> None:
	raise NoNetwork("外部への接続が試みられました。")


class OfflineTranslationTest(unittest.TestCase):
	def test_fresh_translator_translates_without_any_connection_attempt(self) -> None:
		require_model()
		# 製品の読込経路(_load_engines)が外部取得の停止を適用する。試験側では適用しない。
		_load_engines()
		from screen_translation_server.engines import ArgosTranslator

		# 新しいtranslatorは文分割(Stanza)を最初から初期化する。接続を試みれば失敗する。
		with patch.object(socket.socket, "connect", forbid_connect), \
			patch.object(socket, "getaddrinfo", forbid_connect), \
			patch.object(socket, "create_connection", forbid_connect):
			translated = ArgosTranslator("en", "ja").translate("Hello. How are you today?")
		self.assertRegex(translated, JAPANESE)

	def test_missing_stanza_resource_fails_preparation_instead_of_fetching(self) -> None:
		manifest = require_model()
		with tempfile.TemporaryDirectory() as temporary:
			copy = Path(temporary) / "stanza"
			shutil.copytree(argos_stanza_directory(), copy)
			(copy / "en/mwt/combined.pt").unlink()
			resources = StanzaResources(stanza_resources().manifest, lambda: copy)
			loaded: list[object] = []
			lifecycle = EngineLifecycle(
				manifest, model_directory(), stanza_resources=resources,
				engine_loader=lambda: loaded.append(object()) or (object(), object()),
			)
			with patch.object(socket.socket, "connect", forbid_connect):
				with self.assertRaises(Exception):
					lifecycle.prepare()
		self.assertEqual(lifecycle.state, ModelState.FAILED)
		self.assertEqual(loaded, [])
		self.assertIn("Stanza資源", lifecycle.failure_reason or "")
		self.assertNotIn(temporary, lifecycle.failure_reason or "")


if __name__ == "__main__":
	unittest.main()
