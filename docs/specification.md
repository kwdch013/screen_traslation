# 仕様書

## システム概要

本アプリは、ブラウザで利用者が共有した画面、ウィンドウ、またはタブを JPEG フレームとしてローカルの FastAPI サーバーへ送り、OCR、辞書補正、英日翻訳を行って結果を Web 画面へ返す。入力元と結果表示はどちらもブラウザであり、OS 固有の画面一覧や表示ウィンドウには依存しない。

```text
ブラウザの getDisplayMedia
  -> POST /frame
  -> WebCaptureFrameStore
  -> OCR・辞書補正・翻訳パイプライン
  -> TranslationEventPublisher
  -> GET /api/events (SSE)
  -> プレビュー / 字幕リスト
```

既定の構成は、キャプチャが `web`、OCR が `tesseract`、翻訳が `argos`、結果保持が `memory` である。`blank`、`static`、`passthrough`、`console` は CLI またはテスト用に残している。

## アーキテクチャ

### バックエンド

- `main.py`: CLI の解析、単一起動ロック、ブラウザ起動、Web サーバーのライフサイクルを管理する。
- `web_capture.py`: ループバックサーバー、キャプチャセッション、最新フレームと単調増加 `frame_id` を管理する。
- `web_capture_api.py`: フレーム受信 API、共通 HTTP ミドルウェア、フロントエンド配信を組み立てる。
- `web_app_service.py`: `WebAppService` として状態、世代、Runner、設定、辞書、イベント発行元を一元管理する。
- `web_control_api.py`: 開始、停止、再選択、状態取得を公開する。
- `web_settings.py` / `web_settings_api.py`: 公開設定と辞書の検証、永続化、API を担当する。
- `result_events.py` / `web_events_api.py`: 翻訳結果のファンアウトと SSE 配信を担当する。
- `web_pipeline.py`: Web 用のキャプチャ、OCR、翻訳、結果保持、Runner を組み立てる。
- `ocr.py` / `translator.py` / `glossary.py` / `pipeline.py`: OCR、翻訳、辞書補正、キャッシュ、処理頻度制御を担当する。

### フロントエンド

`frontend/src/` の React アプリが次を担当する。

- `useScreenCapture.ts`: 制御 API、`getDisplayMedia`、500ミリ秒間隔のフレーム送信、共有ストリームの停止を管理する。
- `useTranslationEvents.ts`: SSE を購読し、世代と `frame_id` で古い結果を除外して、履歴を新しい順に最大100件へ制限する。
- `TranslationPreview.tsx`: 共有映像を `contain` 表示し、画像座標を映像内座標へ変換して訳文を重ねる。
- `SubtitleList.tsx`: 字幕履歴を表示する。
- `ConfigEditor.tsx` / `GlossaryEditor.tsx`: 設定と辞書を編集する。

FastAPI は `frontend/dist` の `/` と静的ファイルを配信する。`api` と `frame` は予約パスとし、任意パスを SPA へフォールバックしない。ビルド成果物がない場合、`/` は HTTP 503 とビルド手順を返す。

## WebAppService の状態機械

状態は `idle`、`starting`、`awaiting_frame`、`running`、`stopping`、`error` の6種類である。

```text
idle
  -> start -> starting
  -> Runner開始済み・フレーム未受信 -> awaiting_frame
  -> 現行トークンの初回フレーム受信 -> running

awaiting_frame / running
  -> reselect -> awaiting_frame

各状態
  -> stop -> stopping -> idle
  -> 開始・実行・停止失敗 -> error
```

- 制御操作は専用ロックで直列化する。
- 生存中の Runner がある状態での重複開始と、遷移中の不正操作は HTTP 409 にする。
- 再選択は Runner を止めず、キャプチャセッションと世代を更新して新しいフレームを待つ。
- 停止後も2秒以内に Runner が終了しなければ資源への参照を保持したまま `error` にし、新旧パイプラインの並走を防ぐ。
- Runner の非同期エラーは、Runner 自身の世代が現行の場合だけ `error` へ反映する。
- ブラウザは `starting` / `stopping` の間、200ミリ秒間隔で状態を再取得する。`error` では停止操作による復旧を可能にする。

### 世代とセッション

`generation` は表示してよい処理結果の境界である。開始、停止、再選択、異常終了、および開始失敗のロールバックで進行する。世代進行とイベント発行元の旧世代無効化は同じロック内で行う。

キャプチャのセッショントークンも同じ操作で更新し、保存済みフレームを消去する。`frame_id` はセッションをまたいで単調増加し、フレーム消去では巻き戻らない。SSE 購読キューは世代が変わると消去され、後から完了した旧世代の結果も発行されない。

## HTTP API

API と実装ルートは次のとおりである。

| メソッド | パス | 成功時の内容 |
| --- | --- | --- |
| POST | `/frame` | 現行セッションの画像を保存し、本文なしの HTTP 204 を返す。 |
| POST | `/api/control/start` | パイプラインを開始し、状態と現行 `session_token` を返す。 |
| POST | `/api/control/stop` | パイプラインと共有セッションを停止する。任意の `X-Capture-Token` が不一致なら HTTP 409。 |
| POST | `/api/control/reselect` | Runner を維持して世代とセッションを更新し、`awaiting_frame` と新しいトークンを返す。 |
| GET | `/api/status` | `state`、`error_message`、`session_token_valid` を返す。トークン値は返さない。 |
| GET | `/api/events` | `state` と `translation_result` を `text/event-stream` で配信する。 |
| GET | `/api/config` | Web へ公開してよい現在の設定を返す。 |
| PUT | `/api/config` | 公開設定を検証・保存し、設定と `applied: next_start` を返す。 |
| GET | `/api/glossary` | 用語を原文順の `{source, target}` 配列で返す。 |
| POST | `/api/glossary` | 用語を保存し HTTP 201 で返す。空値は HTTP 400、重複は HTTP 409。 |
| DELETE | `/api/glossary/{source:path}` | URL パスの原文を削除し HTTP 204 を返す。未登録なら HTTP 404。 |

制御 API の応答は `state`、`error_message`、`session_token`、`session_token_valid` を持つ。開始・再選択の応答だけが有効なトークン値を含む。サービスが `error` になった操作は HTTP 500 を返す。

### 公開設定

`GET /api/config` と `PUT /api/config` が扱う項目は次に限定する。

- `ocr_fps`
- `min_confidence`
- `ocr_backend`: `static`、`tesseract`、`tesseract_llm_fallback`、`llm`
- `ocr_fallback_min_confidence`
- `translator_backend`: `passthrough`、`argos`
- `llm_model`
- `llm_timeout_seconds`
- `source_language`: `en`
- `target_language`: `ja`
- `target_scope`: `ui_all`
- `external_api_policy`: `local_first_free_only`
- `priority_order`
- `overlay_style`: `font_size`、`text_color`、`background_color`、`overlay_opacity`

`capture_backend`、`overlay_backend`、`target_region`、`llm_base_url`、`translation_log_path` などの内部設定は公開しない。設定は `config/app.json` へ原子的に保存するが、実行中のパイプラインは生成時のスナップショットを使い続ける。

辞書は `config/glossary.json` へ原子的に保存する。登録・削除直後に翻訳キャッシュを失効させ、辞書リビジョン更新前に開始した翻訳結果は更新成功後の SSE へ流さない。

## SSE イベント契約

`GET /api/events` は接続直後に最新の `state` を送る。イベントが15秒ない場合はコメント行 `: heartbeat` を送る。購読者ごとに最大16件のキューを持ち、満杯時は最古のイベントを捨てて処理側を待たせない。

### state

| フィールド | 型 | 内容 |
| --- | --- | --- |
| `generation` | integer | 現在のセッション世代。 |
| `state` | string | `WebAppService` の現在状態。 |
| `error_message` | string / null | `error` の詳細。通常は `null`。 |

```text
event: state
data: {"generation":1,"state":"awaiting_frame","error_message":null}
```

### translation_result

| フィールド | 型 | 内容 |
| --- | --- | --- |
| `generation` | integer | 結果が属するセッション世代。 |
| `frame_id` | integer | 受理したフレームの単調増加 ID。 |
| `captured_at` | number | フレーム保存時の単調時計の秒数。 |
| `processed_at` | number | 結果生成時の単調時計の秒数。 |
| `frame_width` | integer | OCR 対象画像の幅。 |
| `frame_height` | integer | OCR 対象画像の高さ。 |
| `regions` | array | 翻訳領域。0件の結果は現在のプレビュー表示を消去する。 |

各 `regions[]` は `source`、`translated`、`x`、`y`、`width`、`height`、`confidence`、`positioning` を持つ。`positioning` は `available` または `unavailable` である。

```text
event: translation_result
data: {"generation":1,"frame_id":42,"captured_at":123.4,"processed_at":123.5,"frame_width":1280,"frame_height":720,"regions":[{"source":"New Game","translated":"ニューゲーム","x":10,"y":20,"width":120,"height":30,"confidence":0.9,"positioning":"available"}]}
```

ブラウザは世代が進むと現在表示と字幕履歴を消去し、同じ世代では `frame_id` が新しい結果だけを採用する。現在表示は新しい結果が10秒来なければ消去するが、字幕履歴は保持する。SSE 切断時は EventSource の自動再接続を利用する。

## 座標契約

翻訳領域の座標は、サーバーへ送信された画像の左上を `(0, 0)` とする画像ピクセル座標である。デスクトップ全体の座標ではない。

- Tesseract の前処理画像を2倍へ拡大した場合、左上を切り下げ、右下を切り上げて元画像スケールへ戻す。
- `frame_width` と `frame_height` は座標の基準画像寸法である。
- フロントエンドは共有映像をアスペクト比を保った `contain` で表示し、余白を含む変換後の位置へ `available` の領域を重ねる。
- 座標を特定できない LLM OCR の結果は `positioning: unavailable` とし、映像へ重ねずプレビュー下部と字幕リストへ表示する。

## セキュリティ

防御対象は、LAN への意図しない公開、DNS リバインディング、別オリジンからの操作、古いタブからのフレーム・停止要求、巨大画像と低速送信、静的ファイルのパストラバーサル、設定ファイルの破損である。

- 待受先を `127.0.0.1:8765`、uvicorn 1ワーカーに固定する。別アドレスを指定した `WebCaptureServer` は生成できない。
- 全ルートで `Host` を `127.0.0.1`、`localhost`、`::1` のいずれかと妥当なポートに限定する。
- `/frame`、全制御 API、`/api/events`、設定・辞書の更新 API は、`Origin` がある場合に HTTP(S) のローカルオリジンだけを許可する。
- `/frame` は `X-Capture-Token` を定数時間比較し、本文の読み取り前とデコード後の保存直前に検証する。
- 開始、停止、再選択、異常終了でトークンを更新し、旧タブを失効させる。ページ離脱時の停止にもトークンを付ける。
- フレームの `Content-Type` は `image/jpeg` または `image/png` に限定し、宣言と実画像形式の一致を確認する。
- `Content-Length` を必須とし、16 MiB 以下、辺長 10,000 px 以下、総画素数 50,000,000 以下に制限する。
- 接続受理後のヘッダーと本文読み取りを15秒で打ち切る。keep-alive も同じ期限を使う。
- 応答へキャッシュ抑止と `X-Content-Type-Options: nosniff` を付ける。SSE はプロキシのバッファリングも無効化する。
- FastAPI の OpenAPI、Swagger UI、ReDoc を無効化する。
- 静的ファイルは `frontend/dist` 配下へ解決できるパスだけを返す。
- 設定・辞書は同一ディレクトリの一時ファイルへ書いてから置換し、プロセス内ロックで同時更新を直列化する。
- 単一起動ロックをユーザー領域に保持し、同じポートのアプリを重複起動しない。

本アプリには利用者認証や TLS はない。ループバック専用という境界を変更して外部公開してはならない。

## 制約

- 画面共有の開始にはブラウザ上の利用者操作が必要である。
- 共有可否はブラウザ、OS、対象アプリの制約に従う。
- OCR 精度はフォント、背景、解像度、動きに影響される。
- 既定翻訳を使うには Argos Translate の英日モデルが必要である。
- LLM OCR は既定でローカルの OpenAI 互換 API `http://127.0.0.1:8000/v1` を参照し、座標を返さない。
- 設定・辞書ファイルを複数プロセスから同時に編集することは想定しない。
- 現行 Docker Compose はコンテナ内テスト用であり、ホストブラウザ向けのポート公開を定義しない。
