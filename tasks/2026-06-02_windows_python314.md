# 2026-06-02 Windows Python 3.14導入

## 作業内容

- Windows環境で `winget` が利用可能であることを確認した。
- `winget search Python.Python.3.14` でPython 3.14のパッケージを確認した。
- `winget install --id Python.Python.3.14 --source winget --accept-package-agreements --accept-source-agreements` でPython 3.14.5をインストールした。
- `py -0p` でPython 3.14がPythonランチャーに登録されたことを確認した。

## 確認結果

- `py -0p`: Python 3.14が `C:\Users\d\AppData\Local\Programs\Python\Python314\python.exe` として登録済み。
- `py -3.14 --version`: `Python 3.14.5`
- `$env:PYTHONPATH='src'; py -3.14 -m unittest discover -s src/tests`: 15件のテストが通過。
- `$env:PYTHONPATH='src'; py -3.14 -m app.main --text "New Game"`: `New Game` を出力。
- `$env:PYTHONPATH='src'; py -3.14 -m compileall -q src/app`: 成功。
- `$env:PYTHONPATH='src'; py -3.14 -c "from app.desktop_app import DesktopApplication; print(DesktopApplication.__name__)"`: `DesktopApplication` を出力。

## 補足

- インストール後、Pythonランチャーの既定はPython 3.14になった。
- Python 3.13も `C:\Python313\python.exe` として残っている。
