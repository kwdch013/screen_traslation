# Issue #68 client・server・contractsの雛形と旧Web版の共存

## 目的

既存Web版を残したままv1.0用のWindowsクライアント、Linuxサーバー、共通契約ディレクトリを追加し、両方式を同じリポジトリで開発・検証できる初期構成を作る。

## 実施内容

- `client/` に.NET 10.0.402固定のWPF / Core Solution、Coreテスト、Linuxテスト用DockerfileとComposeを追加。
- `server/` にPython 3.14のテスト用Dockerfile / Compose、依存ファイル、パッケージとunittestを追加。
- `contracts/README.md` だけを追加。仕様書・fixtureはIssue #63等へ委ねる。
- Windows runner用 `client-bootstrap.yml` と、リポジトリ構造・開発コマンドの文書を更新。
- Web文書・構造テストとロードマップの要件対応行を更新し、旧Web版と新v1.0ディレクトリの共存を検査する。

## TDDと確認

- 先に文書テストと共存テストを追加して失敗することを確認した。
- `mcr.microsoft.com/dotnet/sdk:10.0.402` でSDK 10.0.402を確認。SDKイメージ同梱Runtimeは10.0.13だったため、runtime 10.0.14イメージからCore runtimeを追加し、`dotnet --list-runtimes` で10.0.14を確認した。
- client ComposeのLinuxコンテナでSolution build (WPF cross-targetを含む) 成功、Core test 1件成功。server ComposeのPython 3.14でunittest 1件成功。
- root CI相当: `mypy src` は77 source filesで成功、`ruff check src` 成功、Python全テスト285件成功 (51 skipped)。関連文書テスト41件成功。
- 既存Webの `docker build --target frontend-test .` も成功。

## 設計上の範囲

設計は `docs/v1.0/design/architecture.md` とADRを参照する。Windows固有APIや製品機能は後続Taskで追加する。既存の `src/`・`frontend/` は変更・撤去せず維持する。
