# Vite 8.2.4への更新

## 目的

既存Dependabot PRのVite更新を、GHSA-vfpm-58rq-9qcgの修正済みバージョン8.2.4へ進め、受入前devに無い勧告を追加しない。

## 変更理由

PR元HEADのVite 8.2.1で `npm audit` を実行すると、GHSA-vfpm-58rq-9qcgが検出された。Vite 8.2.4へ更新することで当該勧告を解消する。

## 変更内容

- `frontend/package.json` のVite範囲を `^8.2.4` に更新。
- `frontend/package-lock.json` のVite解決を8.2.4にし、このVite版が要求する関連依存もlockへ反映。
- 不要な直接依存やoverrideは追加せず、アプリケーションコードは変更しない。

## 検証記録

### 監査

- 元HEADの監査 (`tmp/pr-review/40.npm-audit.json`) でGHSA-vfpm-58rq-9qcgを確認。
- Vite 8.2.4へ更新後、当該勧告は検出されず、受入前dev baseline (`436a43eb88b5a4e1dadbe4cb79ebb8a0bee2370c`) と `via[].url` 集合を比較した新規勧告URLは0件。
- 修正後の監査に残る4件 (Moderate 3 / High 1) は受入前devにもある。`npm audit` 自体は既存勧告のため終了コード1を返す。

### frontend

Node 24.18.0 / npm 11.16.0 のコンテナにCPU 2個を割り当てて実行した。

- `npm install --package-lock-only --save-dev vite@8.2.4` 成功。
- `npm ci` 成功。実行前後の `package-lock.json` SHA-256 は一致。
- `npm run build` 成功。
- `npm run lint` 成功 (警告0、エラー0)。
- `npx vitest run` 成功 (9ファイル、81テスト)。

### Python

PRのPythonソースは最新devから変更していない。既存の `refresh-32-app` Python 3.14検証イメージで `docker run --cpus=2 --rm refresh-32-app` を実行し、247件成功、21件skip。
