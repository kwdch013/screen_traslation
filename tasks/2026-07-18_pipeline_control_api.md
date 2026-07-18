# 2026-07-18 パイプライン実行制御API

## 背景

- Issue #6「ウェブアプリ化(2/9)」として、Tkinterのコールバック内にあった翻訳パイプラインのライフサイクル管理をUI非依存のサービスへ移す。
- ブラウザだけで開始、停止、画面再選択を行えるFastAPIの制御APIと、`--web`エントリポイントを追加する。

## 実装

- `WebAppService`を追加し、`idle / starting / awaiting_frame / running / stopping / error`の状態、Runner、`InMemoryOverlayRenderer`、Webキャプチャセッション、世代番号を一元管理した。
- start / stop / reselectを操作ロックで直列化した。再選択はRunnerを停止せず、トークン、フレーム、世代、異常通知先を更新して`awaiting_frame`へ戻す。
- `PipelineRunner.stop()`後もスレッドが生存している場合は参照を保持し、サービスを`error`にして新Runnerの開始を拒否する。
- Runnerの異常通知先をtick開始時に固定し、再選択前の処理から遅れて届いた異常通知を旧世代として無視するようにした。
- 開始、停止、再選択、異常終了、開始ロールバックで`WebCaptureServer.new_session()`を呼び、旧トークンと旧フレームを失効させる。
- `/api/control/start`、`/api/control/stop`、`/api/control/reselect`、`/api/status`を追加し、Host / Origin検証を適用した。
- 画面選択ページの開始、停止、再選択ボタンを制御APIへ接続した。
- `python -m app.main --web`でforegroundのuvicornを起動できるようにし、既存サーバーと同じh11ヘッダタイムアウトプロトコル、`127.0.0.1`限定、1ワーカー設定を共用した。
- `factory.build_pipeline`へ任意のオーバーレイ注入引数を追加した。既存引数と既定動作は維持している。

## テスト

- Red:
  - 新規テスト追加直後は`app.web_app_service`未実装、`PipelineRunner.set_on_error`未実装、joinタイムアウト後にRunner参照が失われる問題、`run_forever`未実装により失敗することを確認した。
- Green:
  - サービス単体テストで、最初のフレームによる状態遷移、重複start、stop、reselect、世代分離、joinタイムアウト、異常終了、開始ロールバックを確認した。
  - 制御APIテストでライフサイクル、409、旧トークンの403、ステータス、Host / Origin拒否を確認するテストを追加した。
  - Runnerのjoinタイムアウトと異常通知先差し替え、foreground uvicorn設定、`--web`エントリポイントのテストを追加した。
- 最終結果:
  - `docker compose build app`: 成功。
  - `docker compose run --rm app python -m unittest discover -s src/tests`: 141件成功、失敗0件。
  - Python 3.14コンテナで`python -m ruff check src`: 成功(`All checks passed!`)。
  - `PYTHONPATH=src .venv/bin/python -m py_compile src/app/*.py src/tests/*.py`: 成功。

## 対象外

- SSEによる翻訳結果配信と結果イベント契約。
- 設定・辞書API。
- Reactフロントエンド。
- Tkinterデスクトップアプリの撤去。
- OCR座標スケールの修正。
