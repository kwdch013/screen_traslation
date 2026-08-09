# 2026-06-02 多重起動防止とオーバーレイ操作改善

## 作業内容

- 実行中だった `python.exe -m app.main --desktop` の多重起動プロセス4件を停止した。
- Windowsでは名前付きMutex、その他の環境では `config/screen_translation.lock` を使った単一起動ロックを追加した。
- 2つ目以降のデスクトップアプリ起動時は警告を表示して終了するようにした。
- オーバーレイのWindowsクリック透過設定を、ウィンドウ生成後に反映し直すようにした。
- オーバーレイに `WS_EX_TRANSPARENT`、`WS_EX_LAYERED`、`WS_EX_NOACTIVATE` を付け、対象アプリへの操作を妨げにくくした。

## テスト

- 単一起動ロックの単体テストを追加した。
