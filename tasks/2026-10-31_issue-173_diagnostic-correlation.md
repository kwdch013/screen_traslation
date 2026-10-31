# Issue #173 結果配信の診断ログ相関IDと購読解除テストの強化

## 実施内容
- 相関ID復元: `EventHub.publish(..., correlation_id=)` でapp側採番のIDを受け、キューにenvelopeとして保持。溢れ・送信timeoutを `ProcessingObserver.dropped("delivery_queue_overflow" / "delivery_send_timeout")` で相関ID付きに記録。message辞書から値を取り出さない(CodeQL対策)。`publish_state/heartbeat/error` で採番IDをmessageと診断へ同一に渡す。ログに session_id・原文・訳文・画像は出さない。
- error再照合: `result_delivery.py`(app.pyから切り出し)の `publish_error` が `is_frame_current` を通す。
- 購読解除テスト: `with` 内でWebSocketを閉じた直後に `wait_until_empty` を `client.portal` で待つ(timeoutはハング防止のみ)。
- 停止時の待機frame: DELETEで `pipeline.cancel(session, new_generation=None)` を別taskで実行(進行中OCRを待たず応答)。pipelineは待機frame取り出し時に再照合しOCR前に破棄。
- 既存テスト修正: `test_result_completed_after_dictionary_revision_change_is_discarded` は初期revisionが不正(3)で、OCR前再照合により意図通りの状況になっていなかったため2に修正(アサーションは維持)。統合テストの停止試験は `ocr.calls == 1` を断定。

## ハング調査
再開時の200sハングは、`compose run` に `--build` を付けず古いテストイメージを実行していたのが原因(修正前のテストが新しい再照合に当たりstartedを待ち続けた)。再ビルドで解消。

## mutation
| 変更 | 失敗したテスト |
|---|---|
| finallyのunsubscribe除去 | test_stream_connects_pipeline_result_to_text_delivery |
| publish_errorの再照合除去 | test_error_for_a_stale_generation_is_not_delivered |
| 溢れ時のobserver.dropped除去 | test_overflow_log_carries_correlation_id... ほか1 |
| 送信timeoutのobserver.dropped除去 | test_send_timeout_log_carries_correlation_id... |
| DELETEのcancel除去 | test_delete_cancels_the_waiting_frame_and_runs_no_ocr_after_stop |
| 取り出し時の再照合除去 | test_waiting_frame_of_a_stopped_session_is_not_recognized |
| 相関IDをmessage辞書から取得 | test_diagnostic_id_is_never_read_from_the_message_dictionary ほか2 |

## Stanza外部取得の調査(実装せず)
- Argosの `StanzaSentencizer.lazy_pipeline` は `download_method` を渡さず、stanza既定の `DOWNLOAD_RESOURCES` で初期化のたび外部へresources.jsonを取得する。`REUSE_RESOURCES` は resources.json が無い時だけ取得。
- 解決には、製品側でStanza初期化へ `REUSE_RESOURCES` を与える(グローバルなPipeline差し替え or Argos側の拡張)ことと、準備段階(ウォームアップ翻訳)で資源を確実に取得する手順・検証が必要。#81(モデル準備)/#109(信頼済みdigest)と設計をそろえる必要があり、本Taskで膨らませない。別Issue案: 「製品サーバーのStanza資源を準備段階で取得し、実行時は外向き通信なしで翻訳できるようにする」。
