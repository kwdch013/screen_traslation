"""Argos Translateの文分割(Stanza)を、外向き通信なしで動かすための固定。

背景: `argostranslate.sbd.StanzaSentencizer.lazy_pipeline`は`stanza.Pipeline`へ`download_method`を渡さない。
Stanzaの既定(DOWNLOAD_RESOURCES)は初期化のたびに外部(GitHub等)へresources.jsonを取りに行くため、
外向き通信のない製品構成では最初の翻訳が失敗する。Stanza・Argosとも設定でこれを変える手段を持たない。

方針: パッチの適用点をこの1か所に集約する。`argostranslate.sbd`が参照する`stanza`だけを、
`download_method=None`(一切取得しない)を強制する薄い代理へ差し替え、Stanza本体のグローバルな
`stanza.Pipeline`は変えない。資源の取得・検証は準備段階(stanza_resources.py)の役割である。

対象版: argostranslate 1.11.0 / stanza 1.10.1。版の更新でArgosが`sbd.stanza.Pipeline`を使わなくなる、
またはStanzaが引数名を変えた場合は、この関数が例外を出して準備失敗(readiness)にする。
黙って外部取得へ戻らないことは単体試験(test_stanza_offline.py)で確認している。
"""

from __future__ import annotations

from typing import Any


class _OfflineStanza:
	"""`stanza`モジュールの代理。Pipelineだけ外部取得を禁止し、他の属性は本物へ委譲する。"""

	_screen_translation_offline = True

	def __init__(self, real: Any) -> None:
		self._real = real

	def Pipeline(self, *args: Any, **kwargs: Any) -> Any:  # noqa: N802 - 元のAPI名に合わせる
		# 呼び出し側の指定にかかわらず、取得を行わない(None)へ固定する。
		kwargs["download_method"] = None
		return self._real.Pipeline(*args, **kwargs)

	def __getattr__(self, name: str) -> Any:
		return getattr(self._real, name)


def install_offline_stanza() -> None:
	"""Argosの文分割がStanza資源を外部取得しないよう固定する(何度呼んでも同じ結果)。"""
	from argostranslate import sbd

	real = getattr(sbd, "stanza", None)
	if real is None or not callable(getattr(real, "Pipeline", None)):
		raise RuntimeError("Argos Translateの文分割の構成が想定と異なるため、外向き通信なしの固定を適用できません。")
	if getattr(real, "_screen_translation_offline", False):
		return
	sbd.stanza = _OfflineStanza(real)
