"""運用ログ(accessログ・依存ライブラリのログ)に機微情報を出さないための固定設定。

診断ログ(自サーバーのlogger)はsession_id・原文・訳文・画像を出さない設計だが、
運用ログには依存ライブラリ由来の経路が残る。
- uvicornのaccessログは`DELETE /api/v1/sessions/{session_id}`のパスにsession_idを出す。
- argostranslateはINFOで原文・訳文(`info("apply_packaged_translation", input_text)`など)を出す。
"""

from __future__ import annotations

import logging

# 内容を出し得る依存ライブラリのlogger接頭辞。argostranslateは自身のloggerへ明示的にINFOを設定するため、
# rootやhandlerを足す側のレベル指定では抑えられない。
RESTRICTED_LOGGER_PREFIXES = ("argostranslate", "stanza")
# ライブラリがimportより前に作る前提のlogger名。未importでも先にfilterを付けられる。
RESTRICTED_LOGGER_NAMES = ("argostranslate", "argostranslate.utils", "stanza")
# これ未満は捨てる。警告以上の文言は固定文(例: 「…is not available in MiniSBD」)で、内容を含まない。
MINIMUM_LEVEL = logging.WARNING


class _DropBelowWarning(logging.Filter):
	"""ライブラリ側がsetLevelでINFOへ戻しても効くよう、level指定ではなくfilterで捨てる。"""

	def filter(self, record: logging.LogRecord) -> bool:
		return record.levelno >= MINIMUM_LEVEL


_FILTER = _DropBelowWarning()


def restrict_dependency_loggers() -> None:
	"""依存ライブラリのloggerをWARNING未満出力なしに固定する(何度呼んでも同じ結果)。

	ライブラリをimportした後に生成された子loggerも拾えるよう、エンジン読込後にも呼ぶ。
	"""
	names = set(RESTRICTED_LOGGER_NAMES)
	names.update(
		name for name in list(logging.root.manager.loggerDict)
		if name.startswith(RESTRICTED_LOGGER_PREFIXES)
	)
	for name in names:
		logger = logging.getLogger(name)
		logger.setLevel(MINIMUM_LEVEL)
		if _FILTER not in logger.filters:
			logger.addFilter(_FILTER)


class _DropAll(logging.Filter):
	def filter(self, record: logging.LogRecord) -> bool:
		return False


_DROP_ALL = _DropAll()
ACCESS_LOGGER_NAME = "uvicorn.access"


def disable_access_logger() -> None:
	"""uvicornのaccessログを、後からhandlerを足されても出ないよう捨てる。

	`access_log=False`はhandlerを外しpropagateを止めるだけで、運用側がuvicorn.accessや親loggerへ
	handlerを足すとuvicornは出力を再開する(`hasHandlers()`で判定するため)。filterなら残る。
	"""
	logger = logging.getLogger(ACCESS_LOGGER_NAME)
	logger.setLevel(logging.CRITICAL + 1)
	if _DROP_ALL not in logger.filters:
		logger.addFilter(_DROP_ALL)
