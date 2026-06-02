# screen_translation

起動中のWindowsアプリケーション、主にゲーム画面の英語テキストをOCRし、日本語訳を透過オーバーレイで表示するためのアプリケーションです。

## 現在の状態

- キャプチャ、OCR、翻訳、辞書、オーバーレイ、パイプラインを疎結合なモジュールとして分離しています。
- 起動中ウィンドウを選択し、対象領域としてキャプチャできます。
- Tesseract OCR、Argos Translate、Tk透過オーバーレイのアダプタを用意しています。
- 用語辞書はJSONで登録、保存、読み込みできます。
- 初期検証用に、任意テキストをOCR結果として扱うCLIも用意しています。

## ドキュメント

- [仕様書](docs/specification.md)
- [利用手順書](docs/user_guide.md)
- [開発者向け説明書](docs/developer_guide.md)

## 実行

```bash
PYTHONPATH=src python3 -m app.main --text "New Game"
```

辞書登録:

```bash
PYTHONPATH=src python3 -m app.main --add-term "New Game" "ニューゲーム"
```

デスクトップアプリ起動:

```bash
PYTHONPATH=src python3 -m app.main --desktop
```

Argos Translateの英日モデル導入:

```bash
PYTHONPATH=src python3 -m app.main --install-argos-en-ja
```

## テスト

```bash
PYTHONPATH=src python3 -m unittest discover -s src/tests
```

## コンテナ

```bash
docker compose build
docker compose run --rm app
```
