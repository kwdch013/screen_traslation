# Issue #215 モデル・Stanza資源のmanifest更新手順と取得元の差分確認

- ブランチ: `task/215-manifest-update-procedure`（base `develop`）
- 関連: #189/PR #214（Stanza資源）、#81（Argosモデル）、#103（本番コンテナ）、親 #82

## 方針

- 取得元との差分確認は `python -m screen_translation_server.manifest_check`。読み取り専用で、manifestは書き換えない。通信はコマンド実行時だけ（CI・サーバー実行時には入れない）。
- 取得はスタブに差し替えて単体試験する（`FakeFetcher`・疑似レスポンス）。試験では外部通信しない。
- 対象は Argos モデル(`model-manifest.json`)と Stanza 資源(`stanza-manifest.json`)。Tesseract 本体と英語学習データは apt パッケージでmanifest対象外のため、手順に明記した。
- 終了コード: 0一致 / 1差分 / 2設定エラー / 3確認不能。差分は確認不能より優先する。
- CDN(別ホスト)へのHTTPSリダイレクトは通常動作（Hugging Faceで実測）なので差分にしない。HTTPSから外れた場合だけ差分とし、署名付きのリダイレクト先URLは報告に出さない。

## 実行結果（手動、実際の取得元との比較）

2026-11-01、外向き通信のあるコンテナ（`docker run --network bridge`）で実行した。

1. 初回: 5件中2件一致、3件で差分。うち2件(`combined.pt`・`mwt/combined.pt`)はHTTPSのCDNへのリダイレクトを差分扱いにした誤検出で、設計を直した（上記）。
2. `en/tokenize/ewt.pt` は**実際に取得元で差し替わっていた**（manifest: 630886 bytes / `7bc5a152...`、取得元: 634501 bytes / `fc2fed0c...`）。Hugging Faceの`x-linked-etag`・`x-linked-size`およびファイル一覧APIの`lfs.oid`が観測値と一致することを確認し、manifestの当該エントリを更新した（`resolve/v1.10.0` は動く参照であり、コミットSHA固定への変更は別Issueの候補）。
3. 更新後に再実行して5件すべて一致、終了コード0。

つまり、この差分確認コマンドが無ければ、新しい環境の`prepare-model`はewt.ptでSHA-256不一致により失敗していた。ライセンスの確認は対象外（Owner判断）で、本作業では変更していない。

## 受け入れ条件との対応

1. 手順の文書化 → `docs/v1.0/operations.md`「モデル・Stanza資源のmanifest更新手順」。
2. 取得元の更新を検出する手段 → `manifest_check`。
3. 独立レビューとAI Review Gate → PR。

## 検証結果（個別project `t215`、`--build`）

- 単体 `server/compose.test.yml run test`: 290件 OK（skipped=2）。うち `test_manifest_check.py` 24件。
- 新manifest（ewt.pt更新）での実取得: `--profile model run prepare-model` が成功（Argosモデルとstanza資源4件）。続く `--profile integration`（`network_mode: none`）41件 OK。
- 文書整合（ci.ymlのコマンド）45件 OK、現行Web `src/tests` 310件 OK（skipped=76）、ruff（対象ファイル）エラーなし。
- mutation（いずれも試験が失敗）: サイズ比較除去 / SHA比較除去 / SHAの大小区別 / 非HTTPSリダイレクト検出除去 / 終了コードの優先順逆転 / 取得サイズ上限除去 / HTTPS強制除去 / 取得期限除去 / 取得失敗の握りつぶし / 報告へリダイレクト先を出力 / `--target`絞り込み除去。

## 未検証

- 確認コマンドの定期実行の自動化（方針により対象外）。
- ライセンスの確認（Owner判断）。ewt.ptの更新も、取得元の公開値（`x-linked-etag`・`lfs.oid`）との照合で採用した。
