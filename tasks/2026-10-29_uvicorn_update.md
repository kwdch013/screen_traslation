# Uvicorn 0.52 系への対応範囲更新

## 目的

PR #32 の依存範囲 `uvicorn>=0.52.1,<0.53.0` と、非公開 `H11Protocol` API に依存するコードの対応範囲を一致させる。

## 変更理由

`src/app/web_capture_protocol.py` は Uvicorn の非公開 `H11Protocol` API を利用しているため、依存範囲の更新に合わせて対応範囲のコメントも正確に保つ。アプリケーションの挙動は変更しない。

## 変更内容

- `web_capture_protocol.py` の対応範囲を `0.52.1以上0.53未満` に更新。
- 実サーバー互換性テストを含む既存テストを、依存範囲の下限と上限内のバージョンで確認。

## 検証記録

Python 3.14 のコンテナを CPU 2 個に制限して検証した。

- 元HEADでは、既存ログ `tmp/pr-review/32.tests.log` と `tmp/pr-review/32.minimum-tests.log` に Uvicorn 0.52.4 / 0.52.1 での既存単体・実サーバーテスト成功を記録済み。
- 修正HEADでは、Uvicorn 0.52.4 で `python -m unittest discover -s src/tests -p test_web_capture_protocol.py` を実行し、実サーバー互換性テスト4件が成功した。
