# Issue #75 資格情報・TLS更新

## 実施内容

- `CredentialManager`で端末/管理tokenを発行・一覧・失効。平文tokenは発行時だけ返し、台帳にはsalt・verifier hash・role・期限・失効状態を原子的に保存。
- 管理CLIをadmin roleで保護し、資格情報台帳を指定したサーバーは認証要求ごとに状態を再読込。既存idle WebSocketも周期再検証して、失効を1秒以内に反映。
- TLS証明書の一致・DNS SAN・信頼鎖・残存期間検査、同じTLS contextへのSIGHUP再読込、失敗時secure stopを追加。SAN extensionが無い証明書のCN fallbackを拒否する。
- `docs/v1.0/operations.md` と `server/deploy/tls/README.md` に発行・失効・secret供給・ローテーション・復旧を記載。鍵/証明書の実値は追加しない。

## TDD・検証

- 先に資格情報ライフサイクル試験を追加し、管理moduleが未実装の段階で失敗することを確認。
- `docker compose -f server/compose.test.yml run --build --rm test`: 85件成功、3件skip。
- `server/deploy/tls` 読取専用mount付き回帰: SANなし、SAN不一致、残存期間不足、未信頼CA、鍵不一致の拒否と正常系を一時証明書で確認。
- SANなし・CN一致の回帰試験は修正前に成功してしまうことを確認し、DNS SAN必須化後に拒否されることを確認。
- `docker build -t app:ci .` と指定unittest: 306件成功、72件skip。
- mypy `src` / `--platform win32 src`、ruff: 成功。

## 変更境界・未実施範囲

Issue #73の `sessions/` と `test_session_lifecycle.py` は変更していない。`app.py` はこの差分で変更していない。設計書API-008管理HTTP endpoint、secret/certificate provider自動連携、実機での証明書更新・長時間確認は未実施。後続Task #103/#105/#106/#108で本番コンテナ・運用/バックアップ・結合/E2Eを確認する。
