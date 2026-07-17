# 2026-07-17 FastAPIサーバー基盤への移行

## 背景

- Issue #2 の第1段階として、今後のウェブAPI追加に備え、手書きの`http.server`実装をFastAPI + uvicornへ移行する。
- 今回はサーバー基盤のみを対象とし、実行制御API、SSE、React、設定・辞書API、Tkinter撤去は行わない。

## 実装

- `src/app/web_capture.py`
  - `WebCaptureFrameStore` / `WebCaptureSource` の公開インタフェースを維持した。
  - `WebCaptureServer` の`start()` / `stop()` / `new_session()` / `url` / `is_running` / `session_token`を維持し、uvicornをバックグラウンドスレッドで管理するよう変更した。
  - 外部インタフェースへは`127.0.0.1`以外で待ち受けできないようにした。
- `src/app/web_capture_api.py`
  - `GET /`と`POST /frame`のFastAPIルーティングを分離した。
  - 本文を読む前のトークン照合と、保存直前の`accept_frame()`による再照合を行う。
- `src/app/web_capture_security.py`
  - `Host`、`Origin`、`Content-Type`、`Content-Length`、本文サイズ、読み取りタイムアウトを検証する。
  - Pillowの`load()`前に辺長と総画素数を検証し、Content-Typeと実フォーマットを照合する。
  - 本文はストリームで読み、Content-Lengthが偽装されても16MBを超えて蓄積しない。
- `requirements.txt`へ`fastapi`、`uvicorn`、TestClient用の`httpx2`を追加した。
- `Dockerfile`ではArgos Translateが依存するPyTorchをCPU版に固定し、不要なCUDAランタイムを含めないようにした。

## セッションの原子性

- `new_session()`はセッショントークン更新とフレームストア消去を同じセッションロック下で行う。
- `accept_frame()`はトークン照合とストア更新を同じセッションロック下で行う。
- デコード中に`new_session()`が走った競合をテストし、旧フレームが保存されず403になることを確認する。

## テスト

- FastAPI TestClientで正常なJPEG/PNG受理、画面選択ページ配信、各入力防御を検証する。
- 読み取りタイムアウトと本文ストリーム上限を単体テストする。
- uvicornサーバーの起動・停止、公開プロパティ、停止時のトークン失効を検証する。
- 既存`src/tests/test_web_capture.py`の観点は削除せず、実サーバー経由のテストも維持する。
- `docker compose run --rm app`と、コンテナ内の`PYTHONPATH=src python3 -m unittest discover -s src/tests`で115件成功した。
- `ruff check src`でエラーがないことを確認した。

## 対象外

- パイプライン実行制御API、SSE、WebOverlayRenderer、React + Vite、設定・辞書API、Tkinterデスクトップアプリ撤去。

## PR #3 レビュー指摘の修正 (2026-07-18)

- `web_capture_protocol.py`を追加し、TCP接続受理時に初回リクエストの行・ヘッダ受信期限を開始するh11プロトコルを実装した。小刻みなデータ受信では期限を延長せず、h11が完全なRequestへ変換した時だけ解除する。
- `WebCaptureServer`の`start()` / `stop()`を専用ロックで直列化した。起動待ちはローカルのserver/threadを参照し、停止後もスレッドが生存していれば参照を保持して`RuntimeError`にする。
- Host / Originの明示ポートをASCII数字かつ0〜65535に制限し、空ポートを拒否するようにした。
- raw socketによる不完全ヘッダの実サーバーテスト、同時start・起動待ち中stop・joinタイムアウトの競合テスト、Host / Origin異常値の表形式テストを追加した。テストメソッド総数は115件から121件になった。

## PR #3 再レビュー指摘の修正 (2026-07-18)

- `data_received()`の前後で`scope`のオブジェクト同一性を比較し、その受信処理で新しいRequestが完成した場合だけヘッダ期限を解除するようにした。
- 応答完了後に次のリクエスト周期のヘッダ期限を張り直す。uvicornが同時にパイプライン済みRequestを処理した場合は、`scope`の同一性とリクエスト世代番号によって旧周期の期限を解除する。
- 完全なRequestのヘッダ解析後は期限を解除するため、本文受信やASGI処理中にはヘッダ期限を適用しない。リクエスト間は従来のkeep-alive期限と同じ設定値でアイドル接続を閉じる。
- uvicornの非公開`H11Protocol` APIへの依存を`web_capture_protocol.py`に明記し、必要な内部属性が無い場合はプロトコル生成時に失敗させるようにした。
- `requirements.txt`のuvicornを`>=0.35.0,<0.52.0`に制限した。再ビルドしたPython 3.14コンテナでは0.51.0が解決された。
- 2件目の部分ヘッダ、2件のパイプライン、同一keep-alive接続での3フレーム連続POST、内部API前提のテストを追加した。Redとして2件目の部分ヘッダと内部API前提の失敗を確認後に実装し、全125件の成功を確認した。
