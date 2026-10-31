# Issue #85 サーバー全体の設定更新・再起動結合試験

## 目的
R2の各Phaseをまたぎ、認証・準備確認・セッション・翻訳・辞書/設定更新・停止・再起動・再翻訳を永続保存先付きの実サーバーで検証する。

## 実施内容
- `server/tests/integration/test_server_scenario.py`: 全体シナリオ、同時更新、保存失敗、モデル準備失敗、処理中の更新、切断中の更新、`read_until`の全体期限(注入クロック)。
- `server/tests/integration/scenario_support.py`: 再起動(同じSiteで新LiveServer)、ログ捕捉、破棄通知の観測器。
- `live_server.py`: `Site`(CA・証明書・資格情報・保存先を再起動をまたいで保持)、管理token、保存先を環境変数で渡す本番経路、pipelineの遅延生成に対応。既存の試験の呼び出しは変えていない。
- `pipeline_support.read_until` / `test_pipeline_resilience.drain_until_closed`: 全体期限を追加(#80レビュー指摘: recv単位の120秒だけで失敗時に10分以上ハングし得た)。
- `pipeline_case.py`: lifecycleを保持、frameを送らない試験でも`settle`が動く。
- 文書: `docs/v1.0/testing.md`、`docs/v1.0/development.md`。

## 判断
- 「コンテナ再起動」は、名前付きvolumeを使う複数コンテナ実行ではなく、同じ保存先でlistener・Session・辞書・pipelineを作り直すプロセス再起動で再現した。#80のモデル用volumeと同様の外向き通信なし構成を保つため。コンテナ停止・起動をまたぐ永続は未検証と明記した。
- 同期は`Event`・`Barrier`・`Condition`・サーバーloop内の状態待ちのみ。固定sleepは使わない。
- 製品側の課題は本Taskで直さずtesting.mdに記録した(uvicorn accessログのsession_id、argostranslateの訳文INFOログ、`main()`でのready未配線、#189)。

## 試験結果
| 試験 | 結果 |
| --- | --- |
| server integration (`-p "test_*.py"` 全体) | 32件成功(#85の8件を含む) |
| server単体 (compose test) | 180件成功、3件skip |
| app:ci全体 | 310件成功、76件skip |
| v1.0・現行Web文書整合 | 45件成功 |
| mypy `server/src` | 30 source files、問題なし |
| ruff `server/src server/tests` | 成功 |

mutation (各1件を混入し、失敗を確認後に戻した): ①辞書更新でキャッシュを失効しない、②辞書更新をsession revisionへ反映しない、③起動時の確定値復元を外す、④保存失敗の例外文字列をログへ出す、⑤配信前のrevision照合を外す。いずれも#85の試験が失敗した。

## 未検証・課題
testing.mdの「未解決事項・未検証 (#85)」を参照(コンテナ停止・起動をまたぐvolume永続、`main()`のready配線、uvicorn accessログのsession_id、argostranslateの訳文ログ、8時間・性能・Windows E2E)。
