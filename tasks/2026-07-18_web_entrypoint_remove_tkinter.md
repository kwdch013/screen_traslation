# 2026-07-18 ウェブエントリポイント統合と tkinter 撤去（Issue #18）

## 要件

- 引数なしの `python -m app.main` を FastAPI + uvicorn の既定起動にする。
- 起動時に `http://127.0.0.1:8765/` を既定ブラウザで開き、`--no-browser` で抑止できるようにする。
- `SingleInstanceLock` で多重起動を防止し、二重起動時は既存 URL を開いて終了する。
- tkinter、`mss`、`pygetwindow` とデスクトップ固有実装を撤去する。
- 旧設定値を Web 相当へ読み替え、CLI 経路を維持する。
- README と Windows ランチャーを Web 起動へ更新する。

## TDD の経過

### Red

先に次の観点をテストへ追加・更新した。

- 引数なし起動、ブラウザ自動起動、`--no-browser`、二重起動、`--desktop` 撤去。
- `--run-once --text` と `--add-term` の互換性。
- 旧 `mss` / `tk` / `desktop` 設定の読み替え。
- `mss` / `tk` バックエンドの明確な拒否。
- デスクトップモジュール、Python import、依存、Docker `tk`、ランチャーの撤去漏れ検査。
- `BlankCaptureSource` の維持。

実行コマンド:

```bash
PYTHONPATH=src .venv/bin/python -m unittest \
  src.tests.test_main_web \
  src.tests.test_config \
  src.tests.test_factory \
  src.tests.test_desktop_removal \
  src.tests.test_capture
```

結果は 22 件を実行し、旧実装が残っているため 10 failure / 4 error となることを確認した。主な失敗は、引数なし起動がエラーになること、`--desktop` が有効なこと、旧設定値が未変換なこと、旧モジュール・依存が存在することだった。

### Green

実装後、関連サービスとセキュアサーバー設定を含む次の 41 件が成功した。

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v \
  src.tests.test_main_web \
  src.tests.test_config \
  src.tests.test_factory \
  src.tests.test_desktop_removal \
  src.tests.test_capture \
  src.tests.test_web_app_service \
  src.tests.test_web_documentation \
  src.tests.test_web_capture_server_compatibility.WebCaptureServerCompatibilityTest.test_run_forever_uses_same_secure_single_worker_config \
  src.tests.test_web_capture_protocol.HeaderTimeoutProtocolCompatibilityTest
```

結果: `Ran 41 tests ... OK`

既定起動が `WebAppService.server.run_forever()` を通ることと、`run_forever()` が h11 ヘッダタイムアウトプロトコル、`127.0.0.1`、1 worker を設定することを組み合わせて検証した。

追加確認:

- Web 設定・イベント・ドキュメント系 22 件: 成功。
- Web フロントエンド配信・セキュリティ判定 12 件: 成功。
- `PYTHONPATH=src .venv/bin/python -m compileall -q src/app src/tests`: 成功。
- `git diff --check`: 成功。

## 実装内容

- `main.py`
  - 引数なしを Web アプリ起動に変更した。
  - `--no-browser` を追加し、`--desktop` を削除した。
  - Web サーバー起動中は共通の単一起動ロックを保持する。
  - 設定ファイルの指定先が異なっても固定ポートの多重起動を許さないよう、ロックパスは共通にした。
  - 二重起動時は `--no-browser` にかかわらず既存 URL を開き、メッセージを出して終了する。
  - 後片付けが失敗してもロックを解放する。
  - 明示的な `--web` は後方互換として維持した。
- `config.py`
  - 既定値を `capture_backend=web`、`overlay_backend=memory` に統一した。
  - `ui_mode` を設定モデルと保存形式から削除した。
  - 読み込み時だけ旧 `mss` を `web`、旧 `tk` を `memory` へ変換する。
- `factory.py` / `capture.py`
  - `mss` / `tk` バックエンドとウィンドウ追従処理を削除した。
  - 未対応バックエンドは値を含む `ValueError` にした。
  - `BlankCaptureSource`、InMemory / Console renderer は維持した。
- デスクトップ固有ファイルと依存を削除した。
- `start_screen_translation.cmd`
  - venv 作成、依存導入、Tesseract 検出を維持し、引数なし Web 起動へ変更した。
  - Node.js を起動・導入する処理は追加していない。
- README の起動手順を Web アプリへ差し替えた。

## 削除したテストと観点の代替

- `test_desktop_app.py`
  - tkinter のボタン状態、範囲選択、DPI、デスクトップ用組み立て観点は機能ごと撤去した。
  - 起動・停止・再選択、設定・辞書、パイプライン世代管理は既存の WebAppService / Web API / フロントエンドテストで担保する。
- `test_tk_overlay.py` / `test_overlay_opacity.py`
  - Tk パネル描画と Tk 固有の透明度補正は機能ごと撤去した。
  - Web の翻訳表示は既存 React テスト、透明度の入力・保存は設定 API テストと `OverlayStyle` の検証で担保する。
- `test_window.py`
  - `pygetwindow` のウィンドウ探索・タイトル追従は機能ごと撤去した。
  - 共有対象選択はブラウザの `getDisplayMedia` と既存 Web キャプチャテストで担保する。
- `test_capture.py` の `MssCaptureSource`、相対・絶対領域変換テスト
  - `mss` とデスクトップ範囲追従の撤去に伴い削除した。
  - 同ファイルを `BlankCaptureSource` 維持テストへ更新し、Web キャプチャは既存テストで担保する。

## 変更ファイル

### 追加

- `src/tests/test_desktop_removal.py`
- `tasks/2026-07-18_web_entrypoint_remove_tkinter.md`

### 更新

- `Dockerfile`
- `README.md`
- `requirements.txt`
- `start_screen_translation.cmd`
- `src/app/capture.py`
- `src/app/config.py`
- `src/app/factory.py`
- `src/app/main.py`
- `src/app/web_app_service.py`
- `src/tests/test_capture.py`
- `src/tests/test_config.py`
- `src/tests/test_factory.py`
- `src/tests/test_main_web.py`
- `src/tests/test_web_app_service.py`
- `src/tests/test_web_documentation.py`

### 削除

- `src/app/desktop_app.py`
- `src/app/tk_overlay.py`
- `src/app/window.py`
- `src/tests/test_desktop_app.py`
- `src/tests/test_overlay_opacity.py`
- `src/tests/test_tk_overlay.py`
- `src/tests/test_window.py`

## ローカル環境で完了できなかった確認

- 全テスト一括実行は、ソケット生成時の `PermissionError: [Errno 1] Operation not permitted` と、既知の ASGI / `TestClient` 停止問題で完走しなかった。実装に依存しない環境制約であり、依頼者側 Docker での最終確認対象とする。
- Docker CLI は存在したが、Docker API ソケットへの接続が権限不足だったためコンテナテストを実行できなかった。
- `ruff` はローカル環境に未導入だった。`requirements-dev.txt` からの導入はネットワーク名前解決制限で失敗したため、`ruff check src` は依頼者側環境での最終確認対象とする。

## 意図的な対象外

- 段階9で行う README 以外のドキュメント全面更新。
- OCR・翻訳・Web UI の新機能追加。
- フロントエンド実装とビルド成果物の変更。
- コミット、プッシュ、PR 作成。
