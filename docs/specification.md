# 仕様書

## 概要

本アプリは、ブラウザで共有した画面、ウィンドウ、またはタブをキャプチャし、英語テキストをOCRで抽出して、日本語へ翻訳した結果をWeb画面へ表示するアプリである。

初期対象は英語のみとし、翻訳先は日本語のみとする。翻訳対象は字幕に限定せず、対象ウィンドウ全体のUIテキストを扱える構成とする。

## 優先指標

1. GPU速度
2. 遅延
3. 翻訳精度
4. 実装速度

## 実行方式

```text
ブラウザで画面/ウィンドウ/タブを選択
  -> ローカルHTTPサーバーがフレームを受信
  -> OCR
  -> 辞書補正付き翻訳
  -> 翻訳キャッシュ
  -> 透過オーバーレイ表示
```

## モジュール構成

- `capture`: 画面取得を担当する。
- `web_capture`: ブラウザのScreen Capture APIから届く画面フレームの受信を担当する。
- `ocr`: OCRを担当する。
- `translator`: 翻訳を担当する。
- `glossary`: 用語辞書を担当する。
- `overlay`: オーバーレイ表示を担当する。
- `pipeline`: 各モジュールを接続する。
- `result_events`: 翻訳結果と状態イベントの複数クライアント向け配信を担当する。
- `runtime`: パイプラインの開始、停止を担当する。
- `web_app_service`: Web向けパイプラインの状態、世代、キャプチャセッションを管理する。
- `web_events_api`: SSEエンドポイントとheartbeatを担当する。
- `web_frontend`: 画面共有操作、設定、辞書、翻訳結果表示を担当する。
- `factory`: 設定から各モジュールを組み立てる。

## バックエンド

### キャプチャ

- 既定値: `web`
- テスト用: `blank`

`web` はローカルWebページ(`web_capture.WebCaptureServer`)をブラウザで開き、`navigator.mediaDevices.getDisplayMedia` によるブラウザ標準の「画面、ウィンドウ、またはタブを選択」ダイアログでキャプチャ対象を選ぶ。選択後はブラウザがJPEGフレームを定期的にローカルサーバーへ送信し、`WebCaptureSource` が最新フレームを取得する。OS固有のウィンドウ一覧取得には依存しない。`getDisplayMedia` に対応したブラウザ(Chrome / Edge など)が必要となる。

`web` の受信サーバーは FastAPI + uvicorn で動作し、`127.0.0.1` のみで待ち受ける。接続受理から15秒以内に初回リクエストの行・ヘッダを受信できない接続は、h11プロトコル層の絶対期限で閉じる。`POST /frame` はセッショントークン(`X-Capture-Token`)、`Host` / `Origin` ヘッダ検証、`Content-Type` 制限、`Content-Length` 上限、画像の辺長・総画素数上限、画像形式照合、本文読み取りタイムアウトで保護する。開始・停止・再選択のたびにセッショントークンを更新し(`WebCaptureServer.new_session`)、古いブラウザタブから届くフレームは拒否される。CLIの `--run-once` など `web_capture_store` を伴わない非対話経路では `web` を利用できず、テスト用の`blank`など別のキャプチャ方式を明示する必要がある。

### Web制御API

`python -m app.main --web` は、画面選択ページ、フレーム受信API、次の制御APIを同一のローカルサーバーで起動する。インメモリ状態を共有するためuvicornは1ワーカーで動作し、`POST /frame`と同じHost / Origin検証を制御APIにも適用する。

- `POST /api/control/start`: Webキャプチャ用パイプラインを開始し、最初のフレームを待つ。
- `POST /api/control/stop`: パイプラインを停止し、キャプチャセッションを失効させる。任意の`X-Capture-Token`を指定した場合は現行セッションと一致するときだけ原子的に停止し、不一致はHTTP 409とする。トークンなしの要求はユーザー操作用の無条件停止として扱う。
- `POST /api/control/reselect`: パイプラインを維持したままセッションと世代を更新し、新しいフレーム待ちへ戻す。
- `GET /api/status`: 状態、エラーメッセージ、現行セッショントークンの有効性を返す。

状態は`idle → starting → awaiting_frame → running → stopping → idle`で遷移し、開始・実行・停止に失敗した場合は`error`になる。停止要求から2秒後もRunnerスレッドが生存している場合は`idle`へ遷移せず、旧パイプラインとの並走を防ぐ。画面選択ページは`pageshow`で状態を再同期し、`starting` / `stopping`の間は安定状態まで短間隔で再取得する。`error`では停止だけを操作可能にして、保持中のRunnerを停止できれば`idle`へ復旧する。`pagehide`のkeepalive停止にはページのセッショントークンを付け、復元前の旧ページから遅れて届いた停止要求が新しいセッションを止めないようにする。

### 翻訳結果イベントAPI

`GET /api/events`は同一オリジンのブラウザへServer-Sent Events (SSE)を配信する。`EventSource`では任意ヘッダを付けられないためセッショントークンは要求せず、共通ミドルウェアのHost検証と、Originが付く場合のローカルOrigin検証を適用する。接続直後と状態変化時には`state`イベント、OCR処理後には`translation_result`イベントを送る。15秒間送るイベントがない場合はSSEコメント行`: heartbeat`を送信する。

`translation_result`の`data`は次のJSON契約とする。

| フィールド | 型 | 内容 |
| --- | --- | --- |
| `generation` | integer | `WebAppService`のセッション世代。開始、停止、再選択、異常終了で更新する。 |
| `frame_id` | integer | サーバーが受理したフレームの単調増加ID。セッションを消去しても巻き戻さない。 |
| `captured_at` | number | サーバーがフレームを保存した単調時計の秒数。 |
| `processed_at` | number | パイプラインが結果を生成した単調時計の秒数。 |
| `frame_width` | integer | OCR対象画像の幅(ピクセル)。 |
| `frame_height` | integer | OCR対象画像の高さ(ピクセル)。 |
| `regions` | array | 翻訳領域。0件も表示消去イベントとして配信する。 |

各`regions[]`は`source`、`translated`、`x`、`y`、`width`、`height`、`confidence`、`positioning`を持つ。座標はすべて「サーバーへ送信された画像の左上を`(0, 0)`とする画像ピクセル座標」であり、画面全体やデスクトップの絶対座標ではない。Tesseractの前処理で画像を2倍に拡大した場合も、左上端を切り下げ、右下端を切り上げて元画像スケールへ戻すため、1ピクセルの領域を失わない。

`positioning`は、座標をプレビューへ重畳できるTesseract結果では`available`、固定のダミー領域しか持たないLLM OCR結果では`unavailable`とする。フロントエンドは`unavailable`の領域を座標重畳せず、字幕リストとして扱う。

```text
event: translation_result
data: {"generation":1,"frame_id":42,"captured_at":123.4,"processed_at":123.5,"frame_width":1280,"frame_height":720,"regions":[{"source":"New Game","translated":"ニューゲーム","x":10,"y":20,"width":120,"height":30,"confidence":0.9,"positioning":"available"}]}
```

Publisherはアプリ全体で1つを保持し、クライアントごとに上限16件のキューを持つ。キューが満杯の場合は最古のイベントを捨てるため、遅いクライアントが翻訳パイプラインや他クライアントを停止させない。停止時もSSE接続は維持し、`state`イベントで`idle`などの状態を通知する。同一世代の状態通知は通常の有界キュー追加とし、既存の翻訳結果を一括消去しない。世代進行とPublisherの旧世代無効化は同じロック内で行い、世代が変わる場合だけ購読キューを消去して、その後に完了した旧世代の結果も配信しない。

### 設定・辞書API

ブラウザ向けに次のAPIを提供する。全APIに共通のHost検証を適用し、PUT / POST / DELETEには制御APIと同じローカルOrigin検証も適用する。

- `GET /api/config`: 現在の公開設定を返す。`translation_log_path`、`llm_base_url`、`target_region`、Web内部で決定するバックエンド等は公開しない。
- `PUT /api/config`: 指定された公開設定を検証して`config/app.json`へ原子的に保存する。設定は実行状態にかかわらず`applied: next_start`とし、実行中パイプラインは生成時の設定を保持する。
- `GET /api/glossary`: 登録済み用語を登録元文字列順で返す。
- `POST /api/glossary`: `{source, target}`を登録し、`config/glossary.json`へ原子的に保存する。空文字はHTTP 400、登録済み用語はHTTP 409とする。
- `DELETE /api/glossary/{source}`: 用語を削除して保存する。存在しない用語はHTTP 404とする。

辞書はロックでAPIスレッドとパイプラインスレッドの同時アクセスを保護する。登録・削除に成功した時点で実行中パイプラインの翻訳キャッシュを失効させるため、次の翻訳処理から更新内容が反映される。辞書リビジョン更新前に開始した翻訳結果は、更新成功の応答後にはSSEへ配信しない。設定・辞書ファイルは同じディレクトリに一時ファイルを書き、`rename`で置換する。

### OCR

- 既定値: `tesseract`
- テスト用: `static`

`pytesseract` を通じてTesseract OCRを呼び出す。Tesseract本体はOS側にインストールされている必要がある。

### 翻訳

- 既定値: `argos`
- テスト用: `passthrough`

Argos Translateによるローカル翻訳を使う。英日モデルは別途導入する。

### 翻訳結果表示

- 既定値: `memory`
- テスト用: `console`

パイプラインが生成した翻訳結果をSSEでブラウザへ送り、プレビューまたは字幕リストへ表示する。

## 辞書

辞書はJSONで保存する。完全一致した文字列は辞書の訳語を優先し、翻訳後テキストにも部分置換を適用する。

```json
[
  {
    "source": "New Game",
    "target": "ニューゲーム"
  }
]
```

## 設定

既定の設定ファイルは `config/app.json` である。

主な項目:

- `ocr_fps`: OCRの実行頻度
- `min_confidence`: OCR信頼度の下限
- `target_region`: キャプチャ対象領域
- `overlay_style.overlay_opacity`: オーバーレイ透明度
- `capture_backend`: キャプチャ方式
- `ocr_backend`: OCR方式
- `translator_backend`: 翻訳方式
- `overlay_backend`: オーバーレイ方式

## 制約

- 画面共有はブラウザのScreen Capture APIとユーザー操作を必要とする。
- アンチチートがあるゲームではブラウザによる画面取得が制限される場合がある。
- OCR精度はフォント、背景、解像度、エフェクトに影響される。
- Argos Translateの英日モデルが未導入の場合、翻訳は開始できない。
- Dockerコンテナ内だけでホストのゲーム画面を直接取得することは想定しない。
- 設定・辞書ファイルは、Web APIとCLIなど複数プロセスから同時に編集しない。

## 参考

- pytesseract: https://pypi.org/project/pytesseract/
- Argos Translate: https://github.com/argosopentech/argos-translate
