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

## 追加修正

- `cmd.exe` で日本語メッセージが文字化けし、バッチ処理の改行も崩れる問題があったため、`start_screen_translation.cmd` の表示文言をASCIIのみに変更した。
- GUIを開かずに起動ファイルを検証できる `--check` モードを追加した。
- `.\start_screen_translation.cmd --check` を実行し、ランチャー処理が成功することを確認した。
- 確認時点ではTesseract OCR本体がPATHから見つからないため、警告が表示された。
