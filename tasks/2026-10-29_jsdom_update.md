# jsdom 30.0.1 更新時のUndici脆弱性対応

## 目的

Dependabotによる `jsdom` 30.0.1 への更新を維持しながら、間接依存の `undici` を修正済みの8系へ更新し、新しい監査勧告を導入しない。

## 変更理由

jsdom 30.0.1 は `undici` に `^8.9.0` を要求する。PR元HEADのlockfileではUndici 8.10.0が選ばれ、受入前devの監査には無い GHSA-vp8m-p9jh-q5pm が追加されていた。

## 変更内容

- `frontend/package.json` の `jsdom: ^30.0.1` を維持。
- `npm update undici --package-lock-only --no-save` でlockfileのUndiciを8.10.0から8.12.3へ更新。直接依存、override、他の依存更新は追加しない。
- jsdom 30.0.1ではcomputed styleの小数pxが丸められるため、既存の座標テストでinline値を完全一致させ、computed値のみ0.01pxの許容差で確認する。アプリケーションコードは変更しない。

## 検証記録

### 監査

- 受入前dev baseline (`476f95cc03f322d947dfc77ae08bd688e9410284`) と元PR監査の `via[].url` を比較し、元PRで新たに増えたURLは GHSA-vp8m-p9jh-q5pm の1件。
- Undici 8.12.3へ更新後、受入前devと比較した新規勧告URLは0件。GHSA-vp8m-p9jh-q5pmは検出されない。
- npm auditの検出数は元PRの8件 (High 4 / Moderate 4) から7件 (High 3 / Moderate 4) になった。残りは受入前devにもある勧告。

### npm ci / frontend

Node 24.18.0 / npm 11.16.0 のコンテナにCPU 2個を割り当てて実行した。

- `npm ci` 成功。実行前後の `package-lock.json` SHA-256 は一致。
- `npm run build` 成功。
- `npm run lint` 成功 (警告0、エラー0)。
- `npx vitest run` 成功 (9ファイル、81テスト)。
- jsdom 29.1.1のdev baselineでは対象テスト15件が成功。jsdom 30.0.1へ更新した直後はcomputed topの丸め差で1件失敗した。修正後はinline top `151.5625px` の完全一致とcomputed topの許容差確認を行い、81件すべて成功。

### Python

PRのPythonソースは最新devから変更していない。既存の `refresh-32-app` Python 3.14検証イメージで `docker run --cpus=2 --rm refresh-32-app` を実行し、247件成功、21件skip。
