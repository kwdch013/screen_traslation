# Issue #195 運用ログに機微情報を出さない

## 目的
uvicornのaccessログ(DELETEのsession_id)と、argostranslateのINFOログ(原文・訳文)を運用ログから除く。#85の結合試験の除外例外を撤廃する。

## 原因の調査
- uvicornは`access_log=False`でhandlerを外すが、`hasHandlers()`でaccess出力の有無を判定するため、後からhandlerを足されると再開する。
- argostranslateは`argostranslate.utils`のloggerへimport時にINFOを明示する。root側の設定では抑えられず、setLevelで戻されるためlevel固定では不十分。filterで捨てる。
- 警告以上のargos文言は固定文で、原文・訳文は含まない(`info("...", input_text)`系がINFO)。stanzaは`stanza`1つのlogger。

## 実装
- `operational_logging.py`: `restrict_dependency_loggers()`(argostranslate・stanzaをfilterでWARNING以上に固定、既存の子loggerも対象、冪等)、`disable_access_logger()`(`uvicorn.access`をdrop-all)。
- `create_server`で両方を呼び`access_log=False`を渡す。`_load_engines`でも再適用。
- 試験: `server/tests/test_operational_logging.py`、`server/tests/integration/test_operational_log.py`。`scenario_support.py`の`THIRD_PARTY_LOGGERS`と`exclude`、`live_server.py`のaccess logger抑止、`test_server_scenario.py`の`exclude`を撤廃。

## 文書
security.md・operations.md・testing.md・development.mdを更新。

## 検証・mutation
PR本文と`docs/v1.0/testing.md`に記録。
