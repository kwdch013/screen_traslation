# Issue #229 実コンテナ・実エンジンで認証から再起動後の再翻訳までを通すRoadmap結合試験

- ブランチ: `task/229-r2-roadmap-container-e2e`（base `develop` 36fd293）
- 親: Roadmap #70(R2) / 関連: #80, #85, #196, #189, #103

## 方針

- #196のハーネス(`server/tests/container/stack.py`)を拡張し、本番`server/compose.yml`の実コンテナ・実Tesseract/Argosで、認証→ready→session→固定画像の翻訳→辞書更新→停止→コンテナstop/start→再翻訳を1本で通す(`test_container_roadmap.py`)。
- 画像は#80の自前生成画像(`fixtures/pipeline/clear-01.png`)を再利用。frame組み立て・契約照合付き受信は`pipeline_support.py`から`frame_support.py`(標準ライブラリ+jsonschemaのみ)へ切り出して共有し、重複を作らない。`pipeline_support`は再公開するので既存の試験は無変更。
- OCRの揺れで不安定にならないよう、原文は「正規化して期待文を含む」、訳文は「日本語を含む」で判定。辞書訳語だけ完全一致。待機は期限付きポーリング。
- ハーネスに`SERVER_TEST_PROJECT`(プロジェクト名の固定)を追加。後始末の所有者を特定しやすくするため。
- CIには含めない(Docker-in-Docker回避、#196と同じ)。手順は`docs/v1.0/testing.md`。

## 実行結果（手動、対象 develop 36fd293 + 本ブランチ）

環境: ローカルDocker、プロジェクト`t229`、イメージ`screen-translation-server:t229`、モデルvolumeは準備済みvolumeを読み取り専用で複製(`SERVER_TEST_MODELS_FROM`)。このホストはDockerの既定ネットワークアドレスプールが枯渇していたため、自分専用の外部network(固定サブネット)を指す追加composeを`SERVER_TEST_COMPOSE_FILES`で渡した(#196の手順どおり)。

| 実行 | 結果 |
| --- | --- |
| `test_container_roadmap.py` | 1件成功(試験本体 約39秒) |
| `server/tests/container` 全体(#196の試験+本試験、ビルド・複製・準備込み) | 2件成功、97秒 |
| 初回実行 | ネットワークプール枯渇で`compose create`が失敗(環境要因)。外部network指定で解消 |

## mutation（ソース変更+イメージ再ビルド、各1回）

| 変更 | 結果 |
| --- | --- |
| `glossary_runtime.GlossaryRuntime.apply`のキャッシュ`clear()`を除去 | 失敗: 更新後の新規frameの訳が辞書訳語にならず旧訳のまま(`(2, 'ゲームを開始するには…')` != `(2, '実コンテナ通し試験の訳語')`) |
| `app.py`のWSSで旧revision frameの破棄(`if stale_revision`)を無効化 | **検出されず(成功)**。旧revision frameはその後段(pipelineの`_frame_current`・`result_delivery`の再照合)でも破棄されるため、1層の除去では結果の混入が起きない(多重防御)。層ごとの検証はプロセス内の#85(`stale_frame_context`)が担う |
| 再起動でvolumeを使わない | 実施せず(composeの静的検証#103と、本試験の「再起動後に辞書revision 2が残る」確認で代替) |

mutation後は`git checkout`で復元し、最後の全体実行はクリーンなソースから再ビルドして成功した。

## 不具合

新たな製品不具合は見つからなかった。

## 検証

- `docker compose -p t229 -f server/compose.test.yml run --build --rm test`: 328件成功(skip 2)
- 同 integration profile(frame_support切り出し後の既存実エンジン結合): 47件成功
- 文書整合(v1.0・Web・desktop_removal): 45件成功
- `app:t229`(= ci.ymlの`app:ci`相当) `unittest discover -s src/tests`: 310件成功(skip 76)
- `ruff check server/src server/tests`、`mypy server/src`: 問題なし

## 未検証

- 8時間連続稼働・性能・翻訳品質100文(対象外、R4)。
- 画像は明瞭群の1文のみ(複雑背景群は#80の品質評価が担当)。
- `down`→`up`によるコンテナ作り直しは#196の試験が担当(本試験はstop/start)。
