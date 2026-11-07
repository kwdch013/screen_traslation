# Issue #278 サーバーのROI受理上限

## 背景

Issue #277でROIの契約上限が幅1280px・高さ300px・384,000画素へ改訂された。サーバー側の旧1920×1080・2,073,600画素制限を契約に揃え、上限超過を契約済みエラーで明確に拒否する。

## 対応内容

- WSS受信時の寸法・総画素数上限を1280px・300px・384,000画素へ一致させる。
- 境界1280×300を受理し、1281×300と1280×301を拒否する。
- 上限超過frameはdecode/OCR前に`INVALID_IMAGE`を返し、契約どおり接続とsessionを維持する。拒否時にheartbeatを更新しない。
- OCR engineへ直接渡された上限外画像も縮小せず拒否する。
- 拡大後画像の4,000,000画素上限は維持する。
- 運用文書とテスト文書を実装へ揃える。

## 確認

- `server/compose.test.yml` を `docker compose -p t278` で実行し、境界・契約fixture・WSSエラー・既存入力経路を確認する。
- `docker compose -p t278 -f server/compose.test.yml run --build --rm test`: 全365件成功、2件skip。
- OCR実Tesseractの上限ROI直接試験5件は成功。結合ファイル全体では、サーバー結合用Argosモデルが未準備のため`PipelineAfterTimeoutTests.setUpClass`が実行できなかった。
- Mutation: 旧上限へ戻す、幅・高さを±1、画素上限を+1または旧値へ戻す変更を計7通り実施し、すべて対象テストのassertion failureで検出。
- `py_compile`対象Pythonファイル・`git diff --check`は成功。Ruffはこのテストimageおよびホスト環境にインストールされていない。
- ROI受理テスト用PNGを送るWSS経路で、1280×300の正常結果を取得することを確認。
- Claim本文の`claimed-at`は`2026-11-07T17:44:52Z`、GitHub `created_at`は`2026-11-07T17:44:56Z`だった。既存コメントは編集せず、Claim競合判定にはGitHub作成時刻を用いた。
- PR作成後はGitHub CI結果を最新HEADから記録する。Issue/PRをレビュー待ちにし、独立レビュー・承認・mergeはこのTaskでは実施しない。
