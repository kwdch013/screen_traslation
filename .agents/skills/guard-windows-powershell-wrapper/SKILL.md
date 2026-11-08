---
name: guard-windows-powershell-wrapper
description: SSH等からWindows PowerShell 5.1のスクリプトを作成・実行・編集する前に必ず参照する。ネイティブstderrで終了コード記録より先に中断する誤り、予約変数衝突、引用符・文字コード・タスク状態の誤判定を防ぐ。
---

# Windows PowerShellラッパーの再発防止

## 背景
- SSH経由のWindows実機試験で、PowerShell 5.1のネイティブstderr、`-EncodedCommand`の文字コード、展開先、`schtasks`のローカライズ済み表示、予約変数の前提違いによる失敗が複数回発生した。
- `ErrorActionPreference = 'Stop'`でdotnetのstderrをリダイレクトした際、`NativeCommandError`が終了コード記録より先に発生し、試験結果ファイルが残らなかった。

## 守ること
- PowerShell本文は独立した`.ps1`にし、転送後に対象パスと内容をWindows側で読み戻してから実行する。実行ファイルは`$env:TEMP`へ置く。
- `-EncodedCommand`を使うときはUTF-16LEで作る。複雑な本文や日本語をSSHコマンドへ直接埋め込まない。
- `$HOME`、`$PROFILE`等と大小文字だけが異なる変数名を使わない。
- 単引用符内のバッククォートは展開されない。改行編集後は対象コードを読み戻し、リテラルの`` `r`n ``や`` `t ``が残っていないことを確認する。
- PowerShell 5.1でネイティブコマンドのstderrを扱う場合、`$ErrorActionPreference = 'Stop'`のまま`*>`だけでラップしない。ネイティブ実行中は`Continue`にするか`Start-Process -Wait -PassThru`を使う。
- ネイティブ終了コードとログを、エラー判定や後処理より先に保存する。`$LASTEXITCODE`は直後に別変数へ保存する。
- タスクは`Get-ScheduledTask`のStateと実行ログ・終了コードを照合する。ローカライズされた`schtasks`の表示文字列だけで状態を判定しない。

## 作業前チェック
- [ ] `.ps1`を読み戻し、変数名、引用符、転送先、作業ディレクトリを確認した。
- [ ] ネイティブコマンド失敗時も終了コードとログを保存できる実装である。
- [ ] 実行対象と一時ファイルが今回の作業用ディレクトリに限られる。

## 完了前チェック
- [ ] Windows側の変更後コードを読み戻し、文字化けやリテラルエスケープがない。
- [ ] 終了コードとログから試験結果を確認した。
- [ ] 今回作成したタスク・プロセス・ファイルだけを削除し、残存がない。
