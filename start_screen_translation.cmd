@echo off
chcp 65001 >nul
setlocal

set "ROOT=%~dp0"
cd /d "%ROOT%"

echo Screen Translation を起動します。
echo 作業ディレクトリ: %CD%
echo.

if not exist ".venv\Scripts\python.exe" (
    echo .venv が見つからないため、Python 3.14 の仮想環境を作成します。
    py -3.14 -m venv .venv
    if errorlevel 1 (
        echo.
        echo Python 3.14 の仮想環境を作成できませんでした。
        echo Python 3.14 がインストールされ、py -3.14 が使えるか確認してください。
        pause
        exit /b 1
    )
)

".venv\Scripts\python.exe" -c "import mss, PIL, pytesseract, argostranslate, pygetwindow" >nul 2>nul
if errorlevel 1 (
    echo 依存ライブラリを .venv にインストールします。
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo 依存ライブラリのインストールに失敗しました。
        pause
        exit /b 1
    )
)

where tesseract >nul 2>nul
if errorlevel 1 (
    echo.
    echo 注意: Tesseract OCR 本体が PATH から見つかりません。
    echo OCRを使うには Tesseract OCR 本体を別途インストールしてください。
    echo.
)

if not exist "config" mkdir "config"

set "PYTHONPATH=src"
".venv\Scripts\python.exe" -m app.main --desktop
if errorlevel 1 (
    echo.
    echo アプリの起動または実行中にエラーが発生しました。
    pause
    exit /b 1
)

endlocal
