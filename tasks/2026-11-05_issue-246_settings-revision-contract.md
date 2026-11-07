# Issue #246 設定のrevisionと契約文言の整理、実行中のcapture_fps反映

## 目的
1. `contracts/session-state.md`の「`dictionary_revision`は設定/辞書の確定revision」を、実装(設定と辞書は別系列、sessionのrevisionを動かすのは辞書のPUTだけ)に合わせる。
2. 実行中のクライアントが`capture_fps`の変更を取得頻度に反映する方針を決めて実装する。

## 調査(事実)
- サーバー: 設定のPUT確定後、`app.state.capture_fps`と実行中pipelineの`set_capture_fps`を即時更新する(`api/settings.py`)。契約の意図(保存成功で即時active)と一致しており、サーバー修正は不要。
- クライアント: 取得上限は`FrameProcessor`(取得の間引き)、送信上限は`FrameSender`。どちらも`TranslationSessionOptions`(既定2)で固定され、設定の保存は届いていなかった。
- クライアントの上限はサーバーの設定値とは独立に既定2で始まる(設定画面で読み込み・保存するまで揃わない)。

## 方針(A)
保存成功で実行中の取得・送信の上限を、次のフレームから更新する。理由: サーバーが即時に更新するため、クライアントだけ古い値だと不整合になる。REQ-F-008とも合う。詳細は`docs/v1.0/testing.md`。

## 実装
- 契約文言: session-state / README / openapi / api.md。
- `FrameRateLimiter.SetFps`(窓の履歴維持、上限を下げた直後に窓の待ち時間を正しく計算)、`FrameProcessor.SetCaptureFps`、`FrameSender.SetSendFps`、`CaptureSendPipeline.UpdateCaptureFps`、`TranslationSessionHost.ApplyCaptureFps`、`OperationsViewModel.ApplyCaptureFps`。
- `TranslationSettingsViewModel.Saved(int)`は値のみ(revisionを渡さず誤適用を防ぐ)。`RevisionedEditor.SavedValue`。
- 停止中の保存も保持する(パイプラインは開始をまたぐため、次回の開始から使える)。Issue原案の「停止中は何もしない」より、保存の効果が失われない。
- 画面: 設定欄の説明文。

## 未検証・別Task案
- 起動時のクライアントの取得頻度はサーバーの現在値ではなく既定(2)。設定画面を開く前に開始すると、サーバーが1fpsの場合クライアントが超過して送り得る。設定の読み込み成功時にも反映する(または開始時に取得する)別Task案。
- Windows実機の見た目(Owner手順)。
