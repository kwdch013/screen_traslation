# 2026-06-02 クリック起動ファイル追加

## 作業内容

- Windowsでダブルクリック起動できる `start_screen_translation.cmd` を追加した。
- 起動ファイル内で `.venv` がなければPython 3.14の仮想環境を作成するようにした。
- 依存ライブラリが不足している場合のみ、`.venv` 内へ `requirements.txt` をインストールするようにした。
- `PYTHONPATH=src` を起動ファイル内で設定し、`python -m app.main --desktop` を実行するようにした。
- READMEと利用手順書へクリック起動手順を追記した。

## 補足

- `.cmd` は `.exe` ではないが、Windowsでダブルクリック起動できる。
- 依存ライブラリは `.venv` 内へ入るため、Windows全体のPython環境には入らない。
- Tesseract OCR本体はPython依存ライブラリではないため、PATHから見つからない場合は警告を出す。
