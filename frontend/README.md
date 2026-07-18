# フロントエンド

React + Vite + TypeScript で実装した Screen Translation のブラウザ UI です。

## 開発

FastAPI を `http://127.0.0.1:8765` で起動してから実行します。`/api` と `/frame` は Vite のプロキシ経由で FastAPI へ転送されます。

```bash
npm ci
npm run dev
```

## 検証

```bash
npm run lint
npm test
npm run build
```

ビルド成果物は `dist/` に生成され、FastAPI と本番 Docker イメージから配信されます。
