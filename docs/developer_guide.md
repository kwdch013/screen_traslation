# 開発者向け説明書

## 方針

各モジュールは疎結合にし、キャプチャ、OCR、翻訳、オーバーレイを差し替えやすくする。

`contracts.py` のProtocolを境界にしているため、実装を追加する場合は次のいずれかを満たすクラスを作る。

- `CaptureSource`
- `OcrEngine`
- `Translator`
- `OverlayRenderer`

## テスト

```bash
PYTHONPATH=src python3 -m unittest discover -s src/tests
```

## 構文確認

```bash
PYTHONPATH=src python3 -m py_compile src/app/*.py
```

## フロントエンド開発

フロントエンドは `frontend/` の React + Vite + TypeScript プロジェクトで管理する。FastAPI は `frontend/dist` を配信するため、通常起動の前にビルドする。

```bash
cd frontend
npm ci
npm run lint
npm test
npm run build
```

画面を確認しながら開発する場合は、1つ目のターミナルで FastAPI、2つ目で Vite を起動する。

```bash
# ターミナル1: リポジトリ直下
PYTHONPATH=src python -m app.main --web

# ターミナル2
cd frontend
npm run dev
```

Vite は `/api` と `/frame` を `http://127.0.0.1:8765` へプロキシする。Docker イメージは Node ステージでフロントエンドをビルドし、最終 Python イメージには `dist` だけを同梱する。

## 新しいOCRを追加する

1. `src/app/ocr.py` または新規モジュールに `recognize(frame)` を持つクラスを追加する。
2. `TextRegion` のリストを返す。
3. `src/app/factory.py` にバックエンド名を追加する。
4. 依存ライブラリが任意依存の場合は、利用時に `DependencyUnavailableError` を送出する。
5. 変換ロジックをテストする。

## 新しい翻訳器を追加する

1. `translate(text)` を持つクラスを追加する。
2. `GlossaryAwareTranslator` の内側に渡せるようにする。
3. `src/app/factory.py` にバックエンド名を追加する。
4. ローカル処理を優先する。外部APIは完全無料の場合だけ任意設定として扱う。

## 新しいオーバーレイを追加する

1. `render(regions)` と `close()` を持つクラスを追加する。
2. 描画は `TranslationRegion.bounds` を基準にする。
3. オーバーレイ以外のウィンドウ透明度は変更しない。
4. ゲーム操作を妨げないよう、可能な環境ではクリック透過を有効にする。

## コミット方針

作業は小さく分ける。

- 設定や基盤
- キャプチャ
- OCR
- 翻訳
- オーバーレイ
- UI
- ドキュメント

## 現在の実装済み範囲

- ブラウザ経由の画面/ウィンドウ/タブ選択キャプチャ(`web_capture`、既定のcapture_backend)
- Web画面での開始、停止、再選択
- SSEによるプレビューと字幕リストへの翻訳結果配信
- Tesseract OCRアダプタ
- Windows OCRアダプタ
- EasyOCRアダプタ
- Argos Translateアダプタ
- 英日モデル導入コマンド
- 辞書登録と辞書補正
- 翻訳キャッシュ
- OCR FPS制御
- Docker定義

## 未検証範囲

- このLinux/WSL環境では、ブラウザから実際のゲーム画面を共有する操作は検証できていない。
- Dockerビルドとコンテナ内テストは環境にDocker CLIがある場合に確認する。実画面共有は対応ブラウザを使うホスト環境で追加検証する。
