---
name: guard-fresh-container-tests
description: コンテナ内テストを実行する前に、テスト対象ソースを含む最新イメージが使われているか確認する。
---

# コンテナテストの最新ソース確認

## 起動条件

Dockerfileがコピーするソースまたはテストを変更した後、ComposeやDockerでテストを実行するとき。

## 手順

1. Composeのvolume mountが対象ソースをコンテナ内へ反映するか確認する。
2. mountが無い場合は、作業ごとに固有のproject名 (`docker compose -p <task-id> ...`) を指定し、`run --build`または明示的な`docker build`で専用イメージを作る。
3. テスト件数が0、ソース変更が結果へ反映されない、または予期したテストが未発見なら、その結果を成功扱いせず、固有イメージで再実行する。
4. 実行コマンドと対象テストを記録し、終了コードを確認する。
