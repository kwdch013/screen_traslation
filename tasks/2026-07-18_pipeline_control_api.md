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

## PR #7 レビュー指摘の修正

- キャプチャセッション世代とRunner世代を分離し、再選択中に進行していたtickの失敗を同じRunnerの有効な異常として扱うようにした。
- ページ初期化時の状態同期、`pagehide`時のkeepalive停止要求、非同期操作中のボタンガードを追加した。
- Runner停止例外と停止タイムアウトを`error`として保持し、制御APIがHTTP 500を返すようにした。
- `/api/status`へOrigin検証を適用し、ページ側でも応答の`state=error`を失敗として表示するようにした。
- READMEと利用手順書へWebアプリの起動、停止、再選択の最小手順を追記した。
- 各指摘に対応する回帰テストを先に追加し、既存実装での失敗を確認してから修正した。

### Red → Green

- 実`PipelineRunner`で再選択中のtick失敗が`awaiting_frame`に残る失敗を確認し、Runner世代を維持して`error`へ遷移することを確認した。
- ページの状態同期、`pagehide`のkeepalive停止、APIの`error`応答検証、操作中ガードがHTMLに存在しない失敗を確認し、追加後に成功した。
- `runner.stop()`例外が呼び出し元へ漏れる失敗を確認し、Runner参照を保持した`error`応答へ変わることを確認した。
- 停止タイムアウトがHTTP 200になる失敗と、`/api/status`が不正Originを受理する失敗を確認し、それぞれHTTP 500、403になることを確認した。
- READMEと利用手順書にWeb操作手順がない失敗を確認し、追記後に成功した。

### 確認結果

- 更新ソースをマウントしたPython 3.14コンテナで151件成功、失敗0件。
- 指定の`.venv`コマンドは実行したが、ソケット生成禁止による既存12件のエラー後、現行AnyIO/TestClient環境が停止したため中断した。TestClientの停止は最小構成でも再現し、変更コードに依存しないことを確認した。

## 再レビュー指摘の修正

- `/api/control/stop`で任意の`X-Capture-Token`を受け取り、操作ロック内で現行トークンと照合してから停止する契約にした。不一致は、旧ページに停止完了と誤認させないためHTTP 409とし、トークンなしのユーザー操作は従来どおり無条件停止とした。
- `pagehide`のkeepalive停止へセッショントークンを付与し、再選択後に遅れて届く旧セッションの停止が現行Runnerへ影響しないようにした。
- `error`状態では開始・再選択を無効、停止だけを有効にし、初期状態同期でも`error_message`を表示するようにした。
- `pageshow`で状態を再同期し、`starting` / `stopping`では200ミリ秒後の再取得を安定状態まで継続するようにした。

### Red → Green

- 旧トークンを指定した停止が引数未対応で失敗し、pagehideにもトークンがないことを確認した。修正後はHTTP 409となり、現行トークン、状態、Runnerを維持し、現行トークンの停止だけが`idle`へ遷移する。
- `error`で開始が有効・停止が無効になり、初期同期時のエラー詳細も表示されないテスト失敗を確認した。修正後は停止だけが有効になり、`error_message`を表示する。
- `pageshow`同期と遷移中ポーリングが存在しないテスト失敗を確認した。修正後は復元時に同期し、安定状態まで短間隔で再取得する。

### 確認結果

- `.venv`のソケット不要テスト93件: 成功、失敗0件。
- 変更対象の`py_compile`: 成功。
- `TestClient`を使う追加APIテストはサンドボックスのソケット制限により無出力のまま停止するため、15秒で打ち切った。API下層のサービス契約はソケット不要テストで確認した。
- `.venv`には開発依存のruffが未導入のため、ruffは実行できなかった。
