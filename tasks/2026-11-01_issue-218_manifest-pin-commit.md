# Issue #218 モデル・Stanza資源のmanifest取得URLをコミットSHA固定にする

- ブランチ: `task/218-manifest-pin-commit`（base `develop`）
- 関連: #215/PR #217、#189/PR #214、#81、親 #82

## 採用したコミットSHAと照合結果（2026-11-01）

| 取得元 | 固定SHA | 特定方法 |
| --- | --- | --- |
| Hugging Face `stanfordnlp/stanza-en` | `92f1a846e29acaa866ed76e433ede3589115a2a9`（`v1.10.0`タグの指す2025-03-04のコミット） | `/api/models/stanfordnlp/stanza-en/revision/v1.10.0` の`sha` |
| GitHub `stanfordnlp/stanza-resources` | `6c91e03e9281e297a6d7a7d0649a6c7b642058da`（`resources_1.10.0.json`の最新コミット、2025-11-21） | commits API（`path=resources_1.10.0.json`） |

- Hugging Faceのツリー一覧API（固定SHA指定）の`lfs.oid`・`size`と、固定URLから実ファイルを取得したSHA-256・サイズが、現行manifestの値と全4件で一致（combined tokenize 650887 / ewt 634501 / mwt combined 509238 / resources.json 434061）。値の変更は無く、URLだけを変更した。
- 存在しないSHAは404になることを確認。
- 取得したファイルは自分専用の一時ディレクトリに置き、確認後に削除した。

## Argosモデルを対象外にした理由

`argos-net.com`の版付き単一ファイル（`translate-en_ja-1_1.argosmodel`）で、コミット参照の仕組みがない。サイズ・SHA-256検証と`manifest_check`で差し替えを検出する。理由は`docs/v1.0/operations.md`に記載。

## 実装

- `engines/stanza_resources.py`: `is_commit_pinned_url`（HTTPS・Hugging Faceの`resolve/<40桁小文字hex>/`またはraw.githubusercontent.comの`<owner>/<repo>/<40桁hex>/`だけ許可）と`StanzaManifest.unpinned_files()`。実行時の`validate()`は変えない（試験用の偽URLを使う既存試験を保つため）。同梱manifestの固定は単体試験で強制する。
- 試験: 固定形式の可否（タグ・ブランチ・短縮SHA・大文字・別ホスト・http・blob・パス途中のSHAを拒否）、同梱manifestが全件固定、固定SHAの404/410が確認不能（終了コード3）。

## 検証結果

個別project `t218`、すべて `--build`。

- サーバー単体試験: 296件OK（skipped=2、うち新規は固定形式・同梱manifest固定・404/410の確認不能）。
- mutation: (1) `is_commit_pinned_url`を常にTrueにする → 固定形式の2件が失敗。(2) 同梱manifestのewt.ptをタグ参照へ戻す → 同梱manifest固定の2件が失敗。いずれも元に戻して全件OK。
- `prepare-model`: 固定URLでArgosモデルとStanza資源の取得・検証・配置が完了。
- `python -m screen_translation_server.manifest_check`（固定URLで取得元と比較）: 5件中5件一致、終了コード0。
- 実エンジン結合（`network_mode: none`）: 41件OK。
- v1.0・現行Web文書整合テスト45件OK、`app:ci`相当の`src/tests`は310件OK（skipped=76）、ruff全件OK。
- 未検証: Argosモデルの固定（対象外）。固定SHAが実際に消えた場合の実取得（404は存在しないSHAで確認、404/410の分類はスタブ試験）。ライセンス確認はOwner判断で未実施。
