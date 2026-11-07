---
name: guard-container-test-rebuild
description: コンテナ内テストのソースを変更した後、古いDockerイメージを使って結果を誤認しないために使う。
---

# コンテナテストの再ビルド

コンテナへCOPYするソースやDockerfileを変更した後は、変更前に作成したイメージが残っている可能性を前提にする。

## 手順

1. `docker compose run` を直接実行せず、`docker compose build <service>` または `docker compose run --build <service>` を使う。
2. 出力で変更したテストファイルがbuild contextへ含まれたことを確認する。
3. テストの実行件数が想定どおりであることを確認する。`Ran 0 tests`、no tests collected、skipのみの場合は成功と扱わない。
4. shell pipelineを使う場合は`set -o pipefail`を設定し、コンテナの終了コードを保つ。

Dockerfileやテストの追加・変更が無い場合は、既存イメージの再利用でよい。
