---
name: guard-container-unittest-discovery
description: Composeコンテナでunittestの一部または全部を実行する前に必ず参照する。テスト配置先を確認せずimport名を直接指定してImportErrorになる誤りを繰り返したため、正しいdiscover形式と実行結果の判定方法を定める。
---

# Compose内unittest実行の再発防止

## 背景
- 2026-10-30と2026-10-31に、Compose内に存在しないホスト側のテストモジュール名を直接指定し、テストがimportされず失敗した。
- 根本原因: Composeの作業ディレクトリとテストの配置先を確認せず、ホスト上のPython import pathがコンテナにもあると思い込んだ。

## 守ること
- 対象サービスの`working_dir`とテスト配置先をcomposeファイルで確認する。
- ファイル単位の限定実行は`python -B -m unittest discover -s <配置先> -p '<file>.py'`を使う。
- テスト名も限定するときは`-k '<test name>'`を追加する。コンテナ内にpackageがあると確認できない限り、`python -m unittest <module>`を使わない。
- Compose内の限定実行でもdiscover形式を崩さず、コマンドを打つ前に`docker compose ... run --rm <service> python -B -m unittest discover -s <container test dir> -p '<file>.py' -k '<test name>'`の形を確認する。
- 失敗をmutation検出として数える前に出力を確認し、対象テスト実行後のassertion失敗であることを確かめる。ImportErrorやテスト0件は検出と見なさない。

## 作業前チェック
- [ ] compose定義からコンテナ内テスト配置先を確認した。
- [ ] 使用するコマンドが`unittest discover`で始まり、正しい探索先を指定している。
- [ ] Composeで対象を絞る場合もモジュール名の直接指定を使っていない。

## 完了前チェック
- [ ] 終了コードだけでなく、出力で対象テスト名と実行件数を確認した。
- [ ] 失敗確認後にmutation変更を復元し、差分を確認した。

## 悪い例 / 良い例
- 悪い: `python -m unittest tests.test_pipeline_limits.Test.test_case` (コンテナに`tests` packageが無い場合)
- 良い: `python -m unittest discover -s tests -p test_pipeline_limits.py -k test_case`
