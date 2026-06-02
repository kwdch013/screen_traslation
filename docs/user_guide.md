# 利用手順書

## 前提

- Windows環境で実行する。
- Python 3.14を使用する。
- Tesseract OCR本体をインストールする。
- Python依存ライブラリをインストールする。
- Argos Translateの英日モデルを導入する。

## セットアップ

### 1. Python依存ライブラリ

```bash
python -m pip install -r requirements.txt
```

### 2. Tesseract OCR

WindowsではTesseract OCR本体をインストールし、`tesseract` がPATHから実行できるようにする。

確認:

```bash
tesseract --version
```

### 3. 英日翻訳モデル

```bash
PYTHONPATH=src python -m app.main --install-argos-en-ja
```

## 起動

```bash
PYTHONPATH=src python -m app.main --desktop
```

## 基本操作

1. 対象ウィンドウを選ぶ。
2. 必要に応じてOCR FPSとオーバーレイ透明度を調整する。
3. 用語辞書が必要な場合は、英語と日本語を入力して登録する。
4. `開始` を押す。
5. ゲーム画面上に日本語訳のオーバーレイが表示される。
6. 終了する場合は `停止` を押す。

## 辞書登録

CLIからも登録できる。

```bash
PYTHONPATH=src python -m app.main --add-term "New Game" "ニューゲーム"
```

登録内容は `config/glossary.json` に保存される。

## CLI検証

実OCRや実翻訳を使わず、辞書とパイプラインの動作だけ確認する。

```bash
PYTHONPATH=src python -m app.main --text "New Game"
```

1回だけ実行する。

```bash
PYTHONPATH=src python -m app.main --run-once --text "New Game"
```

## Docker

Dockerが導入済みの場合:

```bash
docker compose build
docker compose run --rm app
```

このコンテナはテストや推論環境の再現性確認用である。Windowsゲーム画面の取得や透過オーバーレイ表示はWindowsネイティブ実行を前提とする。

## Dockerインストール

この作業環境ではsudoの対話認証が必要だったため、CodexからDockerを直接インストールできなかった。Ubuntu/WSLでは次を実行する。

```bash
scripts/install_docker_ubuntu.sh
```

実行後、WSLまたはシェルを再起動する。

## トラブルシュート

### `tesseract` が見つからない

Tesseract OCR本体が未導入、またはPATHに入っていない。

### Argos Translateの英日モデルが未導入

次を実行する。

```bash
PYTHONPATH=src python -m app.main --install-argos-en-ja
```

### ウィンドウ一覧を取得できない

`pygetwindow` が未導入、または実行環境がWindowsデスクトップではない可能性がある。

### オーバーレイが表示されない

フルスクリーン排他モードでは表示できない場合がある。ボーダーレスウィンドウまたはウィンドウモードで確認する。
