# Issue #199 readiness指定時のpipeline生成フォールバックを禁止する

## 背景
#194/PR #197 の独立レビュー[medium]。`_ensure_pipeline`が`readiness`指定かつ`engines`がNoneのとき`create_default_pipeline`へ戻り、停止中にフレームが届くとイベントループ上で`build_engines`を再実行し得た。

## 設計
- `lifecycle_readiness.PipelineNotReady`を追加。`_ensure_pipeline`は`readiness`指定時、ready でなければ(既存pipelineがあっても)送出し、エンジンが無ければ既定構成へ退避せず送出する。`readiness`未指定は従来互換。
- WSSのstream: `PipelineNotReady`でフレームを破棄し(`observer.dropped("model_not_ready")`)、`MODEL_NOT_READY`のエラーメッセージ(契約済みcode)を通知して接続は維持。`processing`状態は通知しない。
- 準備失敗ログ: 初回と12回ごと(型名と通算回数のみ)。復旧時にinfo 1回。
- `LifecycleReadiness.started`を公開し、start除去を無限待ちでなくassertで検出。単体試験の待機はdeadline付きに変更。結合試験にも started のassertを追加。

## テスト
- `server/tests/test_pipeline_not_ready.py`(新規)、`server/tests/test_lifecycle_readiness.py`(ログ頻度・回復ログ・deadline化)。
- mutation: 退避の復活(`ready_without_engines`で検出)、ready事前判定の除去、lifespanのstart除去(assert失敗)、ログ頻度制限の除去。いずれも検出。
