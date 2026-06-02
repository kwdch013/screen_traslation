# 2026-06-02 仮想環境でのデスクトップ起動確認

## 作業内容

- Windows環境を直接汚さない方針として、リポジトリ内の `.venv` にPython仮想環境を作成した。
- `.venv` 内の `pip` を更新した。
- `.venv` 内に `requirements.txt` の依存関係をインストールした。
- `.venv` 内のPythonでテストを実行した。
- デスクトップアプリを別PowerShellウィンドウで起動した。

## 確認結果

- `.venv` は `.gitignore` によりGit管理対象外であることを確認した。
- `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m unittest discover -s src/tests` は成功し、15件のテストが通過した。

## 補足

- DockerはこのPowerShell環境では `docker` コマンドが見つからなかったため、今回の確認では使用していない。
- Windowsの実画面キャプチャと透過オーバーレイ表示はOSのウィンドウAPIに依存するため、最終的な実画面確認はWindows上で行う。
