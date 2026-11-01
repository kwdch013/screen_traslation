"""Stanzaを外向き通信なしで使う固定(download_method=None)の単体試験。

Argos Translate(argostranslate.sbd.StanzaSentencizer)はdownload_methodを渡さず、Stanzaの既定は
初期化のたびに外部へresources.jsonを取りに行く。ライブラリ更新でこの前提が崩れたら、ここで検出する。
"""

from __future__ import annotations

import types
import unittest
from typing import Any
from unittest.mock import patch

from screen_translation_server.engines import stanza_offline
from screen_translation_server.engines.stanza_offline import install_offline_stanza


class RecordingPipeline:
	instances: list[dict[str, Any]] = []

	def __init__(self, *args: Any, **kwargs: Any) -> None:
		type(self).instances.append(kwargs)


def fake_stanza() -> types.SimpleNamespace:
	return types.SimpleNamespace(Pipeline=RecordingPipeline, __version__="x")


class OfflineStanzaTest(unittest.TestCase):
	def setUp(self) -> None:
		RecordingPipeline.instances = []
		from argostranslate import sbd

		self.sbd = sbd
		# 試験後に本物へ戻す。
		original = sbd.stanza
		self.addCleanup(setattr, sbd, "stanza", original)

	def test_real_argos_sentencizer_never_requests_download(self) -> None:
		from argostranslate import sbd

		sbd.stanza = fake_stanza()  # type: ignore[assignment]
		install_offline_stanza()
		package = types.SimpleNamespace(from_code="en", package_path=__import__("pathlib").Path("/nonexistent"))
		sbd.StanzaSentencizer(package).lazy_pipeline()  # type: ignore[arg-type]
		self.assertEqual(len(RecordingPipeline.instances), 1)
		self.assertIn("download_method", RecordingPipeline.instances[0])
		self.assertIsNone(RecordingPipeline.instances[0]["download_method"])

	def test_caller_supplied_download_method_is_overridden(self) -> None:
		from argostranslate import sbd

		sbd.stanza = fake_stanza()  # type: ignore[assignment]
		install_offline_stanza()
		sbd.stanza.Pipeline(lang="en", download_method="download_resources")
		self.assertIsNone(RecordingPipeline.instances[0]["download_method"])

	def test_other_attributes_are_delegated_and_install_is_idempotent(self) -> None:
		from argostranslate import sbd

		sbd.stanza = fake_stanza()  # type: ignore[assignment]
		install_offline_stanza()
		first = sbd.stanza
		install_offline_stanza()
		self.assertIs(sbd.stanza, first)
		self.assertEqual(sbd.stanza.__version__, "x")

	def test_fails_closed_when_argos_no_longer_exposes_stanza(self) -> None:
		from argostranslate import sbd

		del sbd.stanza
		with self.assertRaises(RuntimeError):
			install_offline_stanza()

	def test_fails_closed_when_stanza_has_no_pipeline(self) -> None:
		from argostranslate import sbd

		sbd.stanza = types.SimpleNamespace()  # type: ignore[assignment]
		with self.assertRaises(RuntimeError):
			install_offline_stanza()

	def test_real_stanza_pipeline_signature_accepts_download_method(self) -> None:
		"""Stanza更新で引数名が変わると、固定が黙って効かなくなるため検出する。"""
		import inspect

		import stanza

		parameters = inspect.signature(stanza.Pipeline.__init__).parameters
		self.assertIn("download_method", parameters)
		from stanza.pipeline.core import DownloadMethod

		self.assertIn("NONE", DownloadMethod.__members__)

	def test_module_exposes_one_installation_point(self) -> None:
		self.assertTrue(callable(stanza_offline.install_offline_stanza))
		with patch.object(stanza_offline, "install_offline_stanza") as install:
			from screen_translation_server.engines.lifecycle import _load_engines

			with patch("screen_translation_server.engines.build_engines", return_value=(object(), object())):
				_load_engines()
		install.assert_called_once()


if __name__ == "__main__":
	unittest.main()
