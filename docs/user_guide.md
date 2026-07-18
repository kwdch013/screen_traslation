# 利用手順書

## 前提

- Windows環境で実行する。
- Python 3.14を使用する。
- Gitを使用できる。
- Tesseract OCR本体をインストールする。
- Python依存ライブラリをインストールする。
- Argos Translateの英日モデルを導入する。

## セットアップ

### 1. リポジトリ取得

PowerShellで任意の作業ディレクトリへ移動し、リポジトリを取得する。

```powershell
git clone git@github.com:kwdch013/screen_traslation.git
cd screen_traslation
```

SSH設定をしていない場合はHTTPSで取得する。

```powershell
git clone https://github.com/kwdch013/screen_traslation.git
cd screen_traslation
```

### 2. Python仮想環境

Python 3.14で仮想環境を作成して有効化する。

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

`py -3.14` で起動できない場合は、Python 3.14をインストールし、`python --version` でバージョンを確認する。

### 3. Python依存ライブラリ

```powershell
python -m pip install -r requirements.txt
```

### 4. Tesseract OCR

WindowsではTesseract OCR本体をインストールし、`tesseract` がPATHから実行できるようにする。

確認:

```powershell
tesseract --version
```

`tesseract` が見つからない場合は、Tesseract OCRのインストール先をPATHに追加してからPowerShellを開き直す。

### 任意: Windows OCR

Windows標準OCRを使う場合は追加依存を入れる。

```powershell
```

設定ファイルの `ocr_backend` を `windows` にするとWindows OCRを使う。通常のUIフォントではTesseractより高速な場合がある。

### 任意: EasyOCR

GPU EasyOCRを試す場合は、Python 3.13などの別仮想環境を作って追加依存を入れる。

```powershell
py -3.13 -m venv .venv_ocr
.\.venv_ocr\Scripts\Activate.ps1
python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
```

評価コマンド例:

```powershell
$env:PYTHONPATH = "src"
```

### 5. 英日翻訳モデル

```powershell
$env:PYTHONPATH = "src"
python -m app.main --install-argos-en-ja
```

## 起動

### クリックで起動する

リポジトリ直下の `start_screen_translation.cmd` をダブルクリックする。

初回起動時は次を自動で行う。

- `.venv` の作成
- Python依存ライブラリのインストール
- `PYTHONPATH` の設定
- デスクトップアプリの起動

依存ライブラリは `.venv` 内へ入るため、Windows全体のPython環境には入らない。

Tesseract OCR本体がPATHから見つからない場合は警告を表示する。OCRを使うには、Tesseract OCR本体を別途インストールする。

### PowerShellから起動する

PowerShellで仮想環境を有効化し、デスクトップアプリを起動する。

```powershell
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "src"
python -m app.main --desktop
```

### Webアプリとして起動する

```powershell
$env:PYTHONPATH = "src"
python -m app.main --web
```

ブラウザで `画面を選択して開始` を押す。共有対象を変更する場合は `画面を選び直す`、翻訳処理を終了する場合は `共有を停止` を押す。Webサーバー自体はPowerShellで `Ctrl+C` を押して終了する。

`プレビュー`タブでは、位置を取得できた訳文を共有映像へ重ねて表示する。位置を取得できない訳文は映像の下に表示する。`字幕リスト`タブへ切り替えると、原文と訳文の直近履歴を新しい順に確認できる。タブを切り替えても翻訳結果の受信は継続する。

翻訳結果の接続が切れた場合は「翻訳結果を再接続中です。」と表示し、自動で再接続する。共有の停止または画面の再選択を行うと、それまでの重畳と字幕履歴は消去される。

## 基本操作

1. 必要に応じてOCR FPSとオーバーレイ透明度を調整する。
2. 用語辞書が必要な場合は、英語と日本語を入力して登録する。
3. `開始` を押すと既定のブラウザが自動で開く。
4. ブラウザのページで `画面を選択して開始` を押し、翻訳したい画面、ウィンドウ、またはタブを選ぶ。
5. 選択したブラウザのタブは翻訳中も開いたままにする。
6. ゲーム画面上に日本語訳のオーバーレイが表示される。
7. 共有する対象を選び直したい場合は `画面再選択` を押し、ブラウザで選び直す。
8. 終了する場合は `停止` を押す。

## 辞書登録

CLIからも登録できる。

```powershell
$env:PYTHONPATH = "src"
python -m app.main --add-term "New Game" "ニューゲーム"
```

登録内容は `config/glossary.json` に保存される。

## CLI検証

実OCRや実翻訳を使わず、辞書とパイプラインの動作だけ確認する。

```powershell
$env:PYTHONPATH = "src"
python -m app.main --text "New Game"
```

1回だけ実行する。

```powershell
$env:PYTHONPATH = "src"
python -m app.main --run-once --text "New Game"
```

テスト画像OCR評価:

```powershell
$env:PYTHONPATH = "src"
python -m app.evaluate_test_images --engine tesseract
```

## Docker

Dockerが導入済みの場合:

```bash
docker compose build
docker compose run --rm app
```

このコンテナはテストや推論環境の再現性確認用である。Windowsゲーム画面の取得や透過オーバーレイ表示はWindowsネイティブ実行を前提とする。

## Dockerインストール

この作業環境ではsudoの対話認証が必要だったため、CodexからDockerを直接インストールできなかった。最終確認時点ではDocker CLIとComposeは存在したが、Dockerデーモンのソケット権限によりビルドは実行できなかった。

Ubuntu/WSLで未導入、または権限設定をやり直す場合は次を実行する。

```bash
scripts/install_docker_ubuntu.sh
```

実行後、WSLまたはシェルを再起動する。

再起動後に確認する。

```bash
docker info
docker compose version
```

## トラブルシュート

### PowerShellで仮想環境を有効化できない

実行ポリシーにより `Activate.ps1` がブロックされている可能性がある。現在のPowerShellだけ許可してから再実行する。

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### `tesseract` が見つからない

Tesseract OCR本体が未導入、またはPATHに入っていない。

### Argos Translateの英日モデルが未導入

次を実行する。

```bash
PYTHONPATH=src python -m app.main --install-argos-en-ja
```

### ウィンドウ一覧を取得できない

`pygetwindow` が未導入、または実行環境がWindowsデスクトップではない可能性がある(レガシーの`mss`キャプチャを使う場合のみ関係する)。

### ブラウザで画面が選択できない、映像が届かない

- `開始` を押しても既定のブラウザが自動で開かない場合は、ステータス欄に表示されたURL(既定は `http://127.0.0.1:8765/`)を手動でブラウザに入力する。
- ブラウザの画面共有ダイアログでキャンセルした場合は、ページの `画面を選択して開始` を押し直す。
- ページを閉じてしまった場合は、`画面再選択` を押すとブラウザが再度開く。

### オーバーレイが表示されない

フルスクリーン排他モードでは表示できない場合がある。ボーダーレスウィンドウまたはウィンドウモードで確認する。
