# screen_translation

起動中のWindowsアプリケーション、主にゲーム画面の英語テキストをOCRし、日本語訳を透過オーバーレイで表示するためのアプリケーションです。

## 現在の状態

- キャプチャ、OCR、翻訳、辞書、オーバーレイ、パイプラインを疎結合なモジュールとして分離しています。
- 初期検証用に、任意テキストをOCR結果として扱うCLIを用意しています。
- 用語辞書はJSONで登録、保存、読み込みできます。
- 実画面キャプチャ、実OCR、実翻訳、Windows透過オーバーレイは差し替え実装として追加していく前提です。

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

## テスト

```bash
PYTHONPATH=src python3 -m unittest discover -s src/tests
```

## コンテナ

```bash
docker compose build
docker compose run --rm app
```
