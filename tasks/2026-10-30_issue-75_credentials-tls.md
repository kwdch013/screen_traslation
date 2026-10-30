# Issue #75 資格情報・TLS更新

## 実施内容

- `CredentialManager`で端末/管理tokenを発行・一覧・失効。平文tokenは発行時だけ返し、台帳にはsalt・verifier hash・role・期限・失効状態を原子的に保存。
- 管理CLIをadmin roleで保護し、資格情報台帳を指定したサーバーは認証要求ごとに状態を再読込。既存idle WebSocketも周期再検証して、失効を1秒以内に反映。
- TLS証明書の一致・SAN・信頼鎖・期限検査、同じTLS contextへのSIGHUP再読込、失敗時secure stopを追加。
- `docs/v1.0/operations.md` と `server/deploy/tls/README.md` に発行・失効・secret供給・ローテーション・復旧を記載。鍵/証明書の実値は追加しない。

## TDD・検証

- 先に資格情報ライフサイクル試験を追加し、管理moduleが未実装の段階で失敗することを確認。
- `docker compose -f server/compose.test.yml run --build --rm test`: 85件成功、3件skip。
- `server/deploy/tls` 読取専用mount付き回帰: 7件成功。生成した一時CA/leaf証明書の正常検査と鍵不一致拒否を確認。
- `docker build -t app:ci .` と指定unittest: 306件成功、72件skip。
- mypy `src` / `--platform win32 src`、ruff: 成功。

## 変更境界

Issue #73の `sessions/` と `test_session_lifecycle.py` は変更していない。Expected files外の入口/auth変更は、既存CredentialStoreを維持しながらCLI台帳を稼働中認証とTLS再読込へ接続する最小変更。
