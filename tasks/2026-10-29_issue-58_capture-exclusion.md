# Issue #58 Windows 画面取得とキャプチャ除外の調査

## 目的

公式資料で Windows 画面取得 API とオーバーレイ自己キャプチャ除外の制約を確認し、Windows 実機検証の再現手順と記録用雛形を用意する。

## 作業記録

- Issue: [#58](https://github.com/kwdch013/screen_traslation/issues/58)
- Base / Merge target: `develop`
- Branch: `task/58-capture-exclusion`
- Worktree: `tmp/worktrees/issue-58`
- PR: [#125](https://github.com/kwdch013/screen_traslation/pull/125) (`develop` 宛て、Draft、レビュー・merge 未実施、`Closes #58`)
- 対象資料: `docs/v1.0/research/capture-exclusion.md`
- 関連文書: `docs/v1.0/design/adr/0002-windows-client.md` と `docs/v1.0/development.md` から調査資料へリンク。
- 文書テスト: `src/tests/test_v1_documentation.py` に必須出典、OS 条件、実機手順、未実施表記の検査を追加。
- Windows 実機の結果: **未実施(Windows実機が必要、実測は独立 Task [#135](https://github.com/kwdch013/screen_traslation/issues/135))**。Linux 環境のため代用試験は行わない。#135 は本 Task と Windows クライアントの取得・除外実装 #92/#97 が試験可能になった後に実施し、#57 等の設計 Task には依存しない。
- 公式資料と実測を分け、WDA の成功が各取得 API での除外成功を証明しないことを明記する。
- 受入対応: 本 Task は調査・出典・手順書・検証プログラム雛形の用意まで。Windows 実測・方式採否・実測値に基づく設計/利用文書反映は #135 の受入条件へ移した。

## 検証

- Red (レビュー指摘再現): `docker build -t app:ci . && docker run --rm -e PYTHONPATH=/app/src app:ci python -m unittest discover -s src/tests` — 267件で failure 1 / errors 2 / skipped 38。文書を含まない通常イメージで新規文書テストが失敗することを確認。
- Green (通常イメージ): `docker build -t app:ci . && docker run --rm -e PYTHONPATH=/app/src app:ci python -m unittest discover -s src/tests` — 267件 OK、skipped 41。
- Green (文書マウント): `docker build -f tests/ai_gate/Dockerfile -t screen-v1-doc-test . && docker run --rm --cpus=2 --memory=512m -v "$PWD:/workspace:ro" -w /workspace screen-v1-doc-test python -B -m unittest src.tests.test_v1_documentation src.tests.test_web_documentation -v` — 28件 OK。調査資料と文書リンクの3検査を維持。
- TDD / Issue 運用メモ: Work Unit helper の最初の呼び出し時に親 worktree を cwd にしてしまった。正しい issue-58 worktree で helper を再実行し、Claim Comment と helper が同じ ID を使うことを確認した。PR marker・commit trailer も同じ値になることを作成後に照合する。誤った呼び出しの根本原因をローカル `.agents/mistake-log.md` に追記。
