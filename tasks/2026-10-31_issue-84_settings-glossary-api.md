# Issue #84 認証付き設定・辞書APIと実行中反映

## 目的

契約の設定・辞書API(GET/PUT)を認証・権限付きで実装し、更新成功後の新規frameだけに新値を反映する。

## 変更内容

- `api/revisioned.py`: 認可→本文上限(413)→検証(422)→If-Match照合(409+ETag)→原子的保存→同期反映の共通処理。エラー本文は契約fixtureと一致。例外文字列・パス・資格情報は応答/ログに出さない(ログは固定文言のみ)。
- `api/settings.py` / `api/glossary.py`: route登録と反映。`app.py`はroute登録・状態保持・旧revision frameの破棄のみ変更。
- `glossary_runtime.py`: 辞書と翻訳キャッシュを世代として原子的に差し替え、更新前に始まった翻訳をキャッシュへ入れない。
- `SessionManager.set_dictionary_revision`(逆行しない)、`TranslationPipeline.set_capture_fps`を追加。
- 契約: openapiの200応答に`ETag`と`X-Effective-From: next-frame`を追記。
- 保存先は`SCREEN_TRANSLATION_DATA_DIR`。未設定時は認証後に500。
- 既存`test_app.py`の501期待(スタブ)を契約どおり(device PUTは403等)へ更新。

## 判断

- 辞書の「登録/削除」は契約どおり`entries`全置換PUTで表現(個別route無し)。
- 件数・文字数超過は#83の`too_large`に従い413、その他の不正は422。
- 旧revisionのframeは切断でなく破棄(更新直後の送信中frameでstreamが切れないため)。

## Mutation検証

| Mutation | 検出したテスト | 結果 |
| --- | --- | --- |
| 管理権限チェック除去 | test_device_token_cannot_update(settings/glossary) | 検出 |
| If-Match照合を無視 | test_stale_revision_conflicts_*(settings/glossary) | 検出 |
| session revisionを進めない | GlossaryLiveReflectionTest 3件 | 検出 |
| 応答へ内部パスを追加 | test_responses_never_expose_secrets_or_internal_paths | 検出 |
| 翻訳キャッシュ失効を除去 | test_update_invalidates_cache_and_applies_new_terms | 検出 |

## 再レビュー対応(変更要求)

- 指摘1: `ProductionPipelineWiringTest`を追加。pipelineを注入せず、`build_engines`をダブルに差し替えて本番生成経路(`_ensure_pipeline`)をWSSで検証(辞書反映、capture_fps反映)。
- 指摘2: stale frameがpipelineへsubmitされないことをspyで検証。
- 指摘3: 保存と反映を1つのtaskにまとめ`asyncio.shield`で保護。保存スレッドは取消されても止まらず、保存済みなのに未反映の状態を残さないため。取消を模擬するテストを追加。
- 指摘4: 反映できなかった語は件数のみ固定文言でログ(`skipped_count`)。語・訳は出さない。

| 追加Mutation | 検出したテスト | 結果 |
| --- | --- | --- |
| 配線削除(translator_wrapper) | test_glossary_update_reaches_translation_of_production_pipeline | 検出 |
| 配線削除(capture_fps) | test_settings_update_reaches_production_pipeline_rate_limit | 検出 |
| stale分岐のcontinueをpassに変更 | test_late_old_revision_frame_is_dropped_without_closing_stream | 検出 |
| shield除去 | test_cancelled_request_still_applies_committed_glossary | 検出 |
| skipログ削除 | test_skipped_terms_are_logged_as_count_only | 検出 |

## 未実施範囲

実エンジンでの検証は#80/#109、サーバー全体の再起動結合は#85。
