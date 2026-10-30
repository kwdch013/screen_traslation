# Issue #63 画像座標・世代・セッション状態契約

## 目的

混在DPI・負座標・ROI境界と、開始/停止/再選択/再接続/辞書更新をまたいだ結果採否を実装可能な契約として固定する。

## 決定

- 座標契約は物理ピクセル、半開区間、モニター別DPI context、最近傍整数の0から遠ざかる丸めとする。
- ROIは1モニター内に完全包含する場合だけ許可する。境界跨ぎ、隙間、画面外、空矩形は開始前に拒否し、切り詰め・分割をしない。
- 結果採否はsession/generation/frame/revision/client単調時計と現在状態をすべて照合する。停止等の無効化はネットワーク応答前に実施する。
- 辞書revisionを更新した後は旧revision結果を表示せず、次の新規frameから新revisionを用いる。

## 変更対象

- `contracts/coordinates.md`
- `contracts/session-state.md`
- `contracts/fixtures/geometry/coordinate-cases.json`
- `docs/v1.0/design/diagrams/coordinates-roi.drawio` / `.svg`
- `docs/v1.0/design/diagrams/state-session.drawio` / `.svg`
- 既存座標fixtureのPythonテスト、開発/調査/設計文書、Issue作業記録

## 検証

- TDD: Pythonテストへfixture読込検証を先に追加。fixture作成前に期待どおりFileNotFoundで失敗することを確認。
- Python 3.14コンテナで座標fixture検証と関連文書テスト43件を実行し、全件成功。
- CIと同じコンテナコマンドで全unit test 286件、`mypy src`、`mypy --platform win32 src`、`ruff check src scripts tests/ai_gate`を実行し、すべて成功。
- `docker compose run`はDockerの既定アドレスpool枯渇でnetwork作成に失敗したため、同じ `app:ci` イメージを `--network none` で実行。全unit testでは既存のReact配布物を同イメージから一時マウントした。
- draw.io CLI 31.4.2で原本を読み込みSVGへ出力。PNG表示で全体と文字が読める倍率を確認し、不要な重複や文字/線の重なりがないことを確認。
- Markdown相対リンク/既存文書整合テスト、JSON構文、`git diff --check`を確認。

## 作業記録

- 2026-10-30: Issue本文、#57設計、混在DPI調査、既存座標モデルとテストを確認。#68との個別ファイル競合なし。
- 2026-10-30: Claim取得後、TDDテストがfixture未作成で失敗することをPython 3.14コンテナで確認。
- 2026-10-30: 続いてfixtureを作成し、座標既存テストを含む9件が通過。
- 2026-10-30: 最終時点で関連文書テスト43件と全286件、両mypy設定、ruffを再検証。
- 2026-10-30: 親worktree cwdでhelperを余分に呼び出した再発を `.agents/mistake-log.md` に記録し、project guard skillとClaude Code向けlinkを追加。Claimは対象worktree内の正しいWork Unit IDで取得した。
