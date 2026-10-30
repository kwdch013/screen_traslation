# Issue #81 モデル準備・readiness・資源上限

## 対応内容

- モデルmanifestのHTTPS取得先、版、サイズ、信頼済みSHA-256、ライセンス確認を検証し、取得・検証・導入の進捗と失敗状態を管理する。
- エンジン準備時にモデルdigestと実行資源を確認し、Tesseract/Argosを一度だけロード・warmupする。
- healthはプロセス生存、readyはモデルとエンジンの準備完了として契約値を返す関数を追加する。
- CPU 2、メモリ4 GiB、同時処理1件、待機は最新1枚に制限する。準備期限は未導入モデル1800秒、導入済みモデル120秒。
- Dockerfileのビルド時モデル自動導入を除き、明示的なモデル導入に変更する。ComposeテストにCPU/メモリ上限を設定する。

## API配線の境界

別Task #72 が作成中の `api/` には触れない。health/readyのHTTPルート配線は、#72後のAPI担当Task（#79/#84等）で行い、このTaskでは `readiness.py` が契約schema準拠のstatusと応答値を返す関数を提供する。

## 検証

- TDD赤: lifecycle未実装時に追加テストが `ModuleNotFoundError` で失敗。
- `docker compose -f server/compose.test.yml run --build --rm test`: 27件成功、2件skip（Argos英日モデル未導入）。Tesseract実エンジン試験は成功。
- `docker build -t app:ci .` と通常イメージの `unittest discover -s src/tests`: 306件成功、72件skip。
- frontend/dist生成後のread-only mount回帰: 306件成功。通常イメージにはビルド済みfrontendが含まれる一方、リポジトリmountでは生成物が隠れるため、先にfrontend buildを実行。
- `mypy src` / `mypy --platform win32 src`: 各79 source files成功。server追加2 source filesのmypyも成功。
- `ruff check --no-cache src scripts tests/ai_gate server`: 成功。
- 実Argosモデルはtrusted digestとライセンス条件が与えられていないため取得していない。モデルの無い環境でArgos smokeをskipし、fake installer/modelで失敗・検証・準備完了を確認。

## 状態

実装完了・PR作成前。Issue #81 Claim取得済み。作成PRは `develop` がbase。レビュー・mergeは別作業。
