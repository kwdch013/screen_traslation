# Issue #279 クライアントのROI選択制限と案内

## 背景

Issue #277でROI上限は幅1280 px・高さ300 px・384,000画素へ改訂された。クライアントの選択・送信直前検査と利用者向け案内を同じ制限へ揃える。

## 対応内容

- CoreのROI選択とFrameProcessorへ幅・高さ・面積の上限を適用する。
- Windows選択オーバーレイに上限超過理由と字幕帯へ狭める案内を表示する。
- install-client / operations / testing文書を更新し、Windows実機の見た目はOwner確認項目として残す。
- 境界値・各上限超過・選び直し・送信前拒否をTDDと複数mutationで検証する。

## 作業記録

- Claim: `work-unit-id=ef2b402e-be57-4dc6-b8c7-5c1e25e08908`。本文の`claimed-at`は`2026-11-07T18:40:03Z`、GitHub `created_at`は`2026-11-07T18:40:06Z`。Claim本文は編集せず、競合判定はGitHub作成時刻に基づき実施。
- TDD Red: `docker compose -p t279 -f client/compose.test.yml run --build --rm test`で更新した境界試験が旧選択・送信制限に対するassertion failureとなることを確認。
- Windows実機の画面表示確認はOwner手順に残し、合格扱いにしない。

## テスト結果

- 最終確認: `docker compose -p t279 -f client/compose.test.yml run --build --rm test` 成功。Core 1件、Client 749件、Capture/Send・実サーバー関連統合56件、契約4件がすべて成功。
- 既存警告: `SettingsViewModelTests.cs(29,70)` のxUnit1031 (同期的なTask待機) が出た。今回の差分外。
- Mutation (すべてComposeのSDKイメージへ作業treeをmountし、対象試験のassertion failureを確認後に復元): 幅上限1280→1281、幅の独立例1281×299、高さ上限300→301、高さの独立例1000×301、面積定数384,000→384,001、日本語の字幕帯案内の差し替え、送信前拒否ガードの無効化。各変異を対応する境界/案内/送信試験が検出。
- Windows固有WPFはLinuxで実行していない。`windows-client` CIとOwner実機手順で確認する。
- PR #288がmergeされた後、`origin/develop`の`27f20dab9ca3bc917c2ec4a093180703831d07ab`をmergeした。共有のoperations/testing文書は統合後にIssue #279の案内・Owner確認手順を追加した。
