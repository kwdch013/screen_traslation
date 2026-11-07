# Issue #226 フレーム単位の非致命エラーで通信全体を閉じない

- ブランチ: `task/226-nonfatal-frame-errors`（base `develop`）
- 関連: #223、#199、#202、#100

## 変更

- 契約: `contracts/fixtures/stream-error-handling.json`（codeごとの致命/非致命・再試行・未知codeは致命）、README、schema説明、api.md、operations.md。
- クライアント: `StreamErrorPolicy`で分類。`TryAcceptFrameError`を非致命の全codeへ拡張し、受信ループは非致命で止めない。ホストの`FrameFailed`イベントとVMの固定文言通知（種類ごとに10秒に1回）。
- 試験: 契約fixtureの突き合わせ（Python/C#）、トランスポート、通知、契約サーバー結合、実サーバー結合（OCRへ処理失敗を注入）。`KnownGap_FrameLevelError_...`を仕様へ書き換え。

## 判断

- 未知のcodeは致命（安全側）。
- `INVALID_IMAGE`はサーバーがパイプライン上限で送り接続を維持するため非致命。
- `MODEL_NOT_READY`は接続維持と通知まで。一時停止・再開は#202。

## 検証結果

- client: Core 1 / Client.Tests 637 / IntegrationTests(契約サーバー)52 / Contracts 4 件すべて成功。
- server: 349 件成功（skip 2。既存の統合用）。新規 `test_stream_error_handling.py` 5 件。
- 実サーバー結合（`client/compose.real-server.yml`）: 12 件成功・skip 0。新規は OCR へ処理失敗を注入し、`PROCESSING_FAILED` 後も通信が閉じず次のフレームが同じ世代で翻訳されること。
- mutation（client 7 件・server 1 件、いずれも試験が失敗）: 分類の取り違え（PROCESSING_FAILED を致命）/ 致命の PROTOCOL_VIOLATION を非致命へ / 採否のsession照合除去 / 送信済みframe照合除去 / 非致命でも閉じる（受信ループがOCR_TIMEOUTのみ）/ 通知抑制の除去 / 契約サーバー結合で非致命を閉じる / fixtureの OCR_TIMEOUT を致命へ。
- 未検証: Windows実機、`dotnet build ClientのSolution(Windows)` はローカルで未実行（CIの windows-client で確認）。
