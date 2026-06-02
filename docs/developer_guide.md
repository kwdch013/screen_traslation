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

- 対象ウィンドウ選択
- 領域キャプチャ
- Tesseract OCRアダプタ
- Argos Translateアダプタ
- 英日モデル導入コマンド
- 辞書登録と辞書補正
- 翻訳キャッシュ
- OCR FPS制御
- Tk透過オーバーレイ
- デスクトップアプリの開始、停止
- Docker定義

## 未検証範囲

- このLinux/WSL環境ではWindowsの実画面キャプチャ、Tkデスクトップ表示、透過オーバーレイの実表示は検証できていない。
- Dockerビルドとコンテナ内テストは確認済み。Windowsの実画面キャプチャ、Tkデスクトップ表示、透過オーバーレイの実表示はWindowsネイティブ環境で追加検証する。
