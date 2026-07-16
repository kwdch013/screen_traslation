# 2026-07-15 ブラウザ経由の画面選択キャプチャ

## 背景
- これまでの画面選択は、Tkinterの半透明オーバーレイ上でマウスドラッグして矩形範囲を指定する方式だった。
- 「画面をウェブ画面にし、どの画面を取り込むかを選択する方式にしましょう」という要望を受け、ブラウザ標準の画面共有選択(画面/ウィンドウ/タブを選ぶダイアログ)を使う方式へ切り替えることにした。

## 実装
- `src/app/web_capture.py` を追加した。
  - `WebCaptureFrameStore`: ブラウザから届いた最新フレームをスレッドセーフに保持する。
  - `WebCaptureServer`: 画面選択用のWebページ(`GET /`)と、フレーム受信エンドポイント(`POST /frame`)を提供するローカルHTTPサーバー。標準ライブラリの`http.server`のみで実装し、新規依存ライブラリは追加していない。
  - `WebCaptureSource`: `CaptureSource`プロトコルを満たし、`WebCaptureFrameStore`から最新フレームを返す。
  - 画面選択ページは`navigator.mediaDevices.getDisplayMedia`でブラウザ標準の「画面、ウィンドウ、またはタブを選択」ダイアログを開き、選択後は`<video>`プレビューを表示しつつ、一定間隔でフレームをJPEGとして`/frame`へ送信する。
- `src/app/factory.py` の `build_capture_source` / `build_pipeline` に `web_capture_store` 引数を追加し、`capture_backend="web"` のときに `WebCaptureSource` を組み立てられるようにした。
- `src/app/config.py` の `PipelineConfig.capture_backend` の既定値を `mss` から `web` に変更した(保存済み設定ファイルで明示的に`mss`が指定されている場合はそのまま尊重される)。
- `src/app/desktop_app.py` を更新した。
  - `開始` を押すと、`capture_backend` が `web` の場合はTkinterの矩形選択を行わず、`WebCaptureServer` を起動してブラウザを自動で開く。
  - `画面再選択`(旧`範囲再選択`)ボタンは、`web`バックエンドの場合は実行中のパイプラインを止めてからブラウザを再度開き、選び直しを促す。レガシーの`mss`バックエンドでは従来どおりTkinterの矩形再選択フローを使う。
  - 終了時(`終了`ボタン)にWebキャプチャサーバーを停止するようにした。
- ドキュメントを更新した: `docs/specification.md`、`docs/developer_guide.md`、`docs/user_guide.md`、`docs/requirements.md`。

## レビュー対応(codex gpt-5.6-sol による受け入れ判断)
PR #1 を codex(gpt-5.6-sol)に段階的にレビューさせ、以下を修正した。
- 受信防御(`POST /frame`): セッショントークン(`X-Capture-Token`)検証、`Host`/`Origin` 検証(DNSリバインディング・クロスオリジン対策)、`Content-Type` 制限、`Content-Length` 上限、読み取りタイムアウトを追加。
- 画像検証: `load()` 前に辺長・総画素数の上限を検証し、`Content-Type` と Pillow の実フォーマットを照合(形式偽装対策)。
- セッション管理: 開始・停止・再選択・異常終了で `WebCaptureServer.new_session()` によりトークンを更新し、旧タブからの送信を無効化。`accept_frame()` でトークン照合とストア更新を同一ロック下で原子化し、読取・デコード中に `new_session()` が走っても旧フレームを保存しない。
- デスクトップ側の例外安全性: 開始・再選択の途中失敗時に `cleanup_failed_start()` でオーバーレイ破棄とセッション失効。Runnerに世代番号を付け、旧Runnerの遅延エラー通知が新セッションを壊さないよう照合。
- Factory/CLI 整合: `capture_backend='web'` を非対話経路(`--run-once` 等)で使った際に、`mss`/`blank` への設定を促す明確なエラーへ改善。
- 画面選択ページを `src/app/web_capture_page.py` へ分離し、セッショントークンを埋め込むよう変更。

## 未実施・今後の課題
- ブラウザでの実際のgetDisplayMedia選択操作、映像プレビュー表示、フレーム送信は、この開発環境(Linux/ヘッドレス)では実ブラウザによる目視確認ができていない。Windowsネイティブ環境での確認が必要(codexレビューでも残タスクとして合意)。
- レガシーの`mss`バックエンド、および対象ウィンドウ選択(`window.py`)はコードとテストを維持したまま残しており、削除していない。

## 確認
- Pillow・pytesseract を導入し、`PYTHONPATH=src python -m unittest discover -s src/tests` を実行し、88件成功(元77件 + 受信防御・セッション関連13件を追加)。
- `PYTHONPATH=src python -m py_compile src/app/*.py src/tests/*.py` でエラーなし。
- 本環境には `docker` コマンドが無いため `docker compose` は未実行。Python 3.14 で単体テストを実行して代替確認とした。
