"""実行中の翻訳へ辞書revisionを反映し、更新時に翻訳キャッシュを失効させる。"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping, Sequence
import logging
import threading
from typing import Any, Protocol

from app.glossary import Glossary

MAX_CACHE_ENTRIES = 512
_LOGGER = logging.getLogger(__name__)


class _Translator(Protocol):
	def translate(self, text: str) -> str: ...


class GlossaryRuntime:
	"""辞書とキャッシュを同じ世代として原子的に差し替える。

	翻訳はworker threadで走るため、開始時点の世代を控え、完了時に世代が変わっていれば
	結果をキャッシュへ入れない(旧revisionの訳が新revisionのキャッシュに混ざるのを防ぐ)。
	"""

	def __init__(self) -> None:
		self._lock = threading.Lock()
		self._glossary = Glossary()
		self._revision = 1
		self._cache: OrderedDict[str, str] = OrderedDict()

	@property
	def revision(self) -> int:
		with self._lock:
			return self._revision

	@property
	def cache_size(self) -> int:
		with self._lock:
			return len(self._cache)

	def apply(self, entries: Sequence[Mapping[str, Any]], revision: int) -> bool:
		"""新しい辞書を反映する。古いrevisionは無視し、反映したかを返す。"""
		glossary = Glossary()
		skipped = 0
		for entry in entries:
			try:
				glossary.register(entry["source"], entry["target"])
			except ValueError:
				# 予約名など照合できない語は反映対象から外す。保存値は変えない。
				skipped += 1
		if skipped:
			# 語そのものは出さず、反映できなかった件数だけを記録する。
			_LOGGER.warning("glossary_terms_skipped", extra={"skipped_count": skipped})
		with self._lock:
			if revision < self._revision:
				return False
			self._glossary = glossary
			self._revision = revision
			self._cache.clear()
			return True

	def translate(self, base: _Translator, text: str) -> str:
		with self._lock:
			glossary, revision = self._glossary, self._revision
			cached = self._cache.get(text)
			if cached is not None:
				self._cache.move_to_end(text)
				return cached
		exact = glossary.translate_exact(text)
		result = exact if exact is not None else glossary.apply(base.translate(text))
		with self._lock:
			if self._revision == revision:
				self._cache[text] = result
				while len(self._cache) > MAX_CACHE_ENTRIES:
					self._cache.popitem(last=False)
		return result

	def wrap(self, base: _Translator) -> _Translator:
		return _RuntimeTranslator(self, base)


class _RuntimeTranslator:
	def __init__(self, runtime: GlossaryRuntime, base: _Translator) -> None:
		self._runtime = runtime
		self._base = base

	def translate(self, text: str) -> str:
		return self._runtime.translate(self._base, text)


__all__ = ["GlossaryRuntime"]
