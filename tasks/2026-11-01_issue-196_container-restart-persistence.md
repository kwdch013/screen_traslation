# Issue #196 コンテナ再起動をまたぐ永続とセッション初期化の実コンテナ検証

- ブランチ: `task/196-container-restart-persistence`（base `develop`）
- 関連: #85（プロセス再起動の再現に留まった）、#194（起動経路のready）、#195（運用ログ）、#103（本番コンテナ）、#189（Stanza資源・並行中）

## 方針

- 本番 `server/compose.yml` を自分専用プロジェクトで起動し、`docker compose stop`→`start`、`down`→`up`（volume維持）で再起動する。HTTPS/WSSの検証は試験側（ホストのPython）から、一時CA・証明書で行う。
- ハーネス `server/tests/container/stack.py`、試験 `test_container_restart.py`。`SERVER_CONTAINER_TEST=1` が無ければskip。CIには含めない（Docker-in-Dockerが必要）。手順は `docs/v1.0/testing.md`。
- 待機は期限付きポーリング。固定sleepは同期条件にしない。

## 受け入れ条件との対応

1. 実コンテナ stop/start・down/up 後の辞書・設定・revision・台帳の保持と session 初期化 → `test_container_restart.py`。
2. #85 の試験側補完の除去 → `scenario_support.py` は製品の `LifecycleReadiness` を使い、`LogCapture` は `uvicorn.access`・`argostranslate` を除外しない。#194/#195 で撤去済みで、残存なし（grep で確認）。
3. 文書更新 → testing.md / operations.md / development.md。

## 見つかった不具合

- runtime イメージに `contracts/` が無く、sessionのWSS配信が `WSS stream contract is not available` で失敗する。runtime ステージに `COPY contracts/ ./contracts/` を追加し、静的検証を追加した。

## 環境上の制約

- Stanza資源（#189未統合）は起動時に `/models` へ書込もうとするため、本番どおり読み取り専用では ready に到達しない。試験は自分専用に複製したmodels volumeだけ書込可にして重ねる（外向き通信が必要）。#189統合後に外す。
- ホストのDockerネットワークのアドレスプールが枯渇していたため、検証では `SERVER_TEST_COMPOSE_FILES` で自分専用の外部ネットワークを指定した（本番 compose は未変更）。

## 未検証

- 本番構成（modelsを読み取り専用）での実コンテナ ready 到達（#189待ち）。
- ホスト/Dockerデーモン再起動後の自動起動、異常終了（SIGKILL）後の保持。
