# Issue #223 OCR打ち切りを契約のエラーコードで区別し、利用者へ案内する

- ブランチ: `task/223-ocr-timeout-error-code`（base `develop`）
- 関連: #190、#109、#108

## 変更

- 契約: stream `error` の `code` に `OCR_TIMEOUT` を追加（schema・fixture・compatibility・C#検証器）。
- サーバー: `OcrTimeoutError` だけ `OCR_TIMEOUT`、他は `PROCESSING_FAILED`。世代の再照合は従来どおり。
- クライアント: `OCR_TIMEOUT` はstreamを閉じず、送信済み・現行session/世代/revision・5秒以内・重複なしの場合だけ採用。翻訳中のみ固定文言を10秒に1回まで表示。
- 文書: contracts/README、design/api、testing、operations、development。

## 検証

- サーバー単体328件、client単体460件（新規11件含む）、server実エンジン結合47件（`test_ocr_time_budget` が `OCR_TIMEOUT` を確認）。
- mutation: サーバーのcode判定差し替え、通知抑制の除去、clientのcode判定差し替えのいずれも失敗することを確認。

## 判断・懸念

- 旧clientは未知のcodeでstreamを閉じるため混在不可。v1.0未リリースで同時更新前提のためmajorは1のまま。
- 既存clientはframe単位のerror（`PROCESSING_FAILED`含む）をすべて契約違反としてstream断にする。別Taskの対象。
- 手順の逸脱: Claim前に `git worktree add -b` でbranchを作成した（Claimは正しいworktreeで取得）。
- 未検証: Windows実機通し(#108)、`client/compose.real-server.yml` への打ち切りケース追加は未実施。
