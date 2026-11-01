# Issue #189 Stanza資源を準備段階で取得し外向き通信なしで翻訳できるようにする

- ブランチ: `task/189-stanza-offline`（base: develop）
- 親: #76 / 関連: #80, #81, #109, #173

## 背景
ArgosのStanza文分割は`download_method`を渡さず、Stanza既定は初期化のたびに外部へresources.jsonを取りに行く。結合試験は`reuse_resources`を試験側で注入して回避していたが、製品は未対応だった。

## 設計
1. 実行時: `engines/stanza_offline.py`が`argostranslate.sbd.stanza`だけを`download_method=None`強制の代理へ差し替える（Stanza本体は無変更・適用点は1か所）。`_load_engines`が呼ぶ。前提が崩れたら例外→準備失敗。
   - `REUSE_RESOURCES`ではなく`None`を採用: REUSEはresources.jsonが無いと取得し、不足モデルも`download_models`で取得するため、外向き通信なしを保証できない。`None`は一切取得せず、HuggingFace FoundationCacheも`local_files_only`になる。
2. 準備: `engines/stanza_resources.py`（manifest・検証・取得）と`stanza_prepare.py`（管理者CLI）。配置先はArgos導入済みパッケージ配下の`stanza/`。未準備・破損分だけ取得し、サイズ・SHA-256を通ったものだけ`os.replace`。
3. 起動: `EngineLifecycle(stanza_resources=...)`が`prepare`でモデル検証直後に再検証し、失敗ならエンジンを読み込まず準備失敗。`startup.py`は`SCREEN_TRANSLATION_STANZA_MANIFEST`を必須化。
4. 試験: 単体 `test_stanza_{resources,offline,readiness,prepare}.py`、結合 `test_offline_translation.py`。`use_installed_stanza_resources`を削除。`prepare_model.py`は製品と同じ`stanza_prepare.prepare`で資源を置く（旧: 試験側の1回翻訳でStanza自身に取得させていた）。

## manifestの値について
`tests/fixtures/pipeline/stanza-manifest.json`のサイズ・SHA-256は、準備段階で取得元から観測した値（resources.jsonと英語のtokenize combined/ewt、mwt combined）であり、配布元が保証する信頼済みdigestではない。ライセンスの確認は対象外。

## 検証（個人project `t189`）
結果はPR本文に記載。mutation: download_method強制の除去、install呼び出し除去、verify呼び出し除去、SHA検証除去、サイズ検証除去（SHAと等価のため生存＝等価変異）、startup配線除去、取得後検証除去。

## 未検証
- 実機（Windows/Linux実運用環境）での外向き通信遮断下の長時間運用。
- 英語以外の言語の資源（manifestは英日のみ）。
- stanza-resources `main`上の`resources_1.10.0.json`が将来変更された場合は、SHA-256不一致で準備が失敗する（意図した動作）。
