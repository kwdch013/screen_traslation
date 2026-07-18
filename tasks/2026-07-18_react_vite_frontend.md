# React + Vite フロントエンド基盤

## 対応 Issue

- Issue #12「ウェブアプリ化(5/9): React+Viteフロントエンド基盤を構築する」
- 作業ブランチ: `feat/react-vite-frontend`
- コミットは依頼どおり実施しない。

## 要件整理

- Python 文字列テンプレートを廃止し、React + Vite + TypeScript へ現行の画面共有・制御機能を移植する。
- 開始・再選択 API 応答からのみセッショントークンを取得する。
- FastAPI が `/` で `index.html`、ハッシュ付き assets と dist 直下の実ファイルを提供し、未知パスは 404 にする。
- `/api/*` と `/frame` はフロントエンド配信から除外し、従来の API ルートで処理する。
- Docker、CI、Dependabot、README、開発ガイドをフロントエンド構成へ対応させる。
- 翻訳表示と設定編集の実装は段階6・7の対象とし、今回はタブの骨組みだけを用意する。

## TDD 記録

### Red: React 機能移植

- `frontend/src/App.test.tsx` に、初期状態同期、3タブ、画面選択、500ms JPEG送信、送信中ガード、再選択トークン更新、403停止、pagehide keepalive停止のテストを先に追加した。
- 初期 Vite 画面には対象 UI が存在せず、6件すべて失敗することを確認した。

### Green: React 機能移植

- API クライアントと `useScreenCapture` を分離して実装した。
- 旧テンプレートの観点を維持するため、操作中ガード、エラー状態のボタン制御、遷移状態の200ms再同期も追加した。
- `npm test`: 13件成功。

### Red: FastAPI 配信

- `src/tests/test_web_capture_page.py` を、React index、ハッシュ付き asset、SPA fallback、予約パス除外、成果物欠落時エラーの検証へ置き換えた。
- `WebCaptureServer(frontend_dist=...)` が未実装のため6件が `TypeError` で失敗することを確認した。

### Green: FastAPI 配信

- `web_frontend.py` に予約パスへマッチしないフロントエンド配信ルートを実装した。当初の SPA fallback は後述の未知パス 404 対応で廃止した。
- この環境では既知の `TestClient` 停止が再現したため、配信ルートのエンドポイントとルートマッチを直接検証する6件へ置き換えて成功を確認した。既存の `TestClient` 利用テストは Docker 環境での最終確認が必要。

### Red → Green: 未知パスの 404 応答

- `test_web_capture_page.py` の SPA fallback テストを未知パス 404 のテストへ変更し、現行実装が `200 != 404` で失敗することを確認した。
- `/` は `index.html`、assets と dist 直下の実ファイルは該当ファイル、それ以外は 404 を返すよう修正した。
- API 予約パスを後から登録されるルートへ渡す制御と、`index.html` 欠落時の明確な 503 エラーは維持した。
- `/`、ハッシュ付き asset、dist 直下ファイル、未知パス、API 予約パス、成果物欠落を含む配信テスト7件が成功した。

### Red → Green: Docker / CI / Dependabot

- `test_frontend_infrastructure.py` の4件がすべて失敗することを確認した。
- Node 24 のビルドステージ、CI の lint/test/build、npm Dependabot、生成物の `.dockerignore` 除外を追加後、4件すべて成功した。

## 実装内容

- React UI に開始・停止・再選択、プレビュー、状態メッセージ、3タブの骨組みを追加した。
- `getDisplayMedia` の映像を canvas へ描画し、JPEG品質0.8、500ms間隔で `/frame` へ送信する。
- フレーム送信と制御操作の多重実行をそれぞれガードした。
- 再選択前の遅延403や、セッションを所有しないタブのpagehideが現行セッションを停止しないよう保護した。
- FastAPI のテンプレート埋め込みを削除し、`frontend/dist` のファイル配信へ変更した。
- クライアントサイドルーティングを使用しないため SPA fallback は行わず、未知パスを 404 にした。
- Vite 開発プロキシ、Docker マルチステージ、CI、Dependabot、開発手順を追加した。

## 検証結果

- `npm test`: 成功、13件。
- `npm run lint`: 成功。
- `npm run build`: 成功。ハッシュ付き JS/CSS と `index.html` を生成。
- `PYTHONPATH=src .venv/bin/python -m unittest src.tests.test_frontend_infrastructure`: 成功、4件。
- `PYTHONPATH=src .venv/bin/python -m unittest src.tests.test_web_capture_page src.tests.test_frontend_infrastructure`: 成功、11件。
- `PYTHONPATH=src .venv/bin/python -m unittest src.tests.test_web_capture_page src.tests.test_frontend_infrastructure src.tests.test_web_capture_api.WebCaptureSecurityTest`: 成功、13件。
- `PYTHONPATH=src .venv/bin/python -m py_compile src/app/web_frontend.py src/tests/test_web_capture_page.py src/tests/test_frontend_infrastructure.py`: 成功。
- 実サーバーを使用する未知パス・HTTP protocol の3件は、依頼どおり Docker 環境での最終確認を依頼者側で行う。
- 変更周辺の Python テスト: 成功、27件。
- Python 全テスト: 115件以上の進行後、`TestClient` 系で実行基盤から終了コードが返らず未完了。
- `ruff check src`: `.venv` に ruff がなく未実行。新規パッケージのインストールは行っていない。
- `npx eslint .`: プロジェクトに ESLint と TypeScript parser/config がなく、ネットワーク待ちで完了しなかった。キャッシュ済み ESLint 単体も設定不足で実行不可。`npm run lint` の Oxlint は成功。
- Docker ビルド: Docker ソケットへの接続権限がなく未実行。

## 対象外

- 翻訳結果をプレビューへ重畳する UI。
- 字幕リストの実データ表示。
- 設定・辞書の編集 UI。
- tkinter の撤去。

## PR #13 レビュー指摘の修正

### Red

- pagehide後の遅延開始応答、アンマウント後の遅延画面選択、未解決フレーム送信中の再選択を追加し、後続処理・ストリーム・送信ガードが残る失敗を確認した。
- start / stop / reselect の409応答を追加し、`detail` が状態として誤適用され、`/api/status` が再同期されない失敗を確認した。
- 初期 `/api/status` の正規なerror状態を追加し、通信失敗の文言として表示される失敗を確認した。
- `index.html` の外部シンボリックリンクを追加し、dist境界外のファイルが200で配信される失敗を確認した。`../` とURLエンコードされた遡及パスの回帰テストも追加した。
- Dockerfileのステージ関係とCIの名前付きステップを標準ライブラリで構造解析し、`frontend-test` ステージとコンテナ検証・ホスト構成テストの不足を確認した。

### Green

- マウント状態と操作世代を各非同期処理で検証し、無効化後のトークンをkeepalive停止、遅延取得したストリームを即時停止するようにした。
- フレーム送信をAbortControllerと共有世代へ紐付け、停止・再選択時に旧送信を破棄できるようにした。
- API応答のstateを実行時検証し、409では従前状態を壊さず `/api/status` から再同期するようにした。初期error状態はサービスエラーとして表示する。
- `index.html` を含む配信対象を解決後のdist配下に限定した。
- npm依存復元・distビルド・フロント検証のDockerステージを共有し、CIのフロント検証を `frontend-test` ターゲットのビルドへ移した。構成テストはホストでも必ず実行する。

### 検証結果

- `npx vitest run`: 20件成功。
- `npm run lint`: 成功。
- `npm run build`: 成功。
- `PYTHONPATH=src .venv/bin/python -m unittest src.tests.test_web_capture_page src.tests.test_frontend_infrastructure src.tests.test_web_capture_api.WebCaptureSecurityTest`: 16件成功。
- 変更したPython 3ファイルの `py_compile`: 成功。
- Dockerでの最終確認は依頼者側で実施する。
