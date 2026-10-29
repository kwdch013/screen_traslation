# Issue #58 Windows 画面取得とキャプチャ除外の調査

## 目的

公式資料で Windows 画面取得 API とオーバーレイ自己キャプチャ除外の制約を確認し、Windows 実機検証の再現手順と記録用雛形を用意する。

## 作業記録

- Issue: [#58](https://github.com/kwdch013/screen_traslation/issues/58)
- Base / Merge target: `develop`
- Branch: `task/58-capture-exclusion`
- Worktree: `tmp/worktrees/issue-58`
- 対象資料: `docs/v1.0/research/capture-exclusion.md`
- 関連文書: `docs/v1.0/design/adr/0002-windows-client.md` と `docs/v1.0/development.md` から調査資料へリンク。
- 文書テスト: `src/tests/test_v1_documentation.py` に必須出典、OS 条件、実機手順、未実施表記の検査を追加。
- Windows 実機の結果: **未実施(Windows実機が必要)**。Linux 環境のため代用試験は行わない。
- 公式資料と実測を分け、WDA の成功が各取得 API での除外成功を証明しないことを明記する。
- 受入対応: 実機結果・方式採否・記録担当/OS条件の実測値と設計/利用文書反映はWindows実機が必要なため未完了。PR本文でも該当条件は未チェックにする。

## 検証

- 文書テスト追加後、資料がない状態で `PYTHONPATH=src python3 -m unittest src.tests.test_v1_documentation.CaptureExclusionResearchTest` を実行し、失敗を確認。
- Green: `PYTHONPATH=src python3 -m unittest src.tests.test_v1_documentation.CaptureExclusionResearchTest` — 2件成功。
- コンテナ文書回帰: `docker build -f tests/ai_gate/Dockerfile -t screen-v1-doc-test . && docker run --rm --cpus=2 --memory=512m -v "$PWD:/workspace:ro" -w /workspace screen-v1-doc-test python -B -m unittest src.tests.test_v1_documentation src.tests.test_web_documentation -v` — 28件成功。
- TDD / Issue 運用メモ: Work Unit helper の最初の呼び出し時に親 worktree を cwd にしてしまった。正しい issue-58 worktree で helper を再実行し、Claim Comment と helper が同じ ID を使うことを確認した。PR marker・commit trailer も同じ値になることを作成後に照合する。誤った呼び出しの根本原因をローカル `.agents/mistake-log.md` に追記。
