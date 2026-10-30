# Issue #72 認証・TLS前提・入力制限

## 目的

新Linuxサーバーの認証境界と通信入力の上限を実装し、資格情報や不正画像を処理エンジンへ渡す前に拒否する。

## 要件・設計との対応

- REQ-F-009 / REQ-F-010、REQ-NF-006 / REQ-NF-007 / REQ-NF-009。
- ADR-0004のTLS 1.2以上、端末/管理role分離、256-bit以上の不透明token、salt付きverifier、許可Host/Origin、認証失敗の情報最小化を実装。
- `contracts/README.md`、`contracts/fixtures/binary-message-boundaries.json`、`contracts/schemas/frame-metadata.schema.json`のHTTP本文/WSS message/画像/ROI境界を入力検査へ反映。
- `docs/v1.0/design/architecture.md`の#72対応とREQ-NF要件対応表、および`docs/v1.0/design/security.md`・`docs/v1.0/design/api.md`に記載されたTLS、Host/Origin、認証後decodeの順序に整合。

## 実装内容

- `security/auth.py`: 256-bit token生成、salt付きSHA-256 verifier作成、定数時間比較、期限/失効/role検証、汎用認証失敗、環境設定からのHost/Origin/TLS証明書読込、TLS 1.2以上を強制。
- `api/input_limits.py`: HTTP JSON 1 MiB、画像4 MiB、ROI寸法/画素数、STF1 binary header・metadata・総byte上限、metadata型/UUID/重複key、PNG/JPEG実形式/実寸法を検証。TLS/Host/Origin/role資格情報の共通認証入口を通ってから画像decodeする。
- `test_security.py` / `test_input_limits.py`: TDDで認証/権限/TLS/Host/Origin、秘密値非露出、fixture境界、偽装画像、ROI、認証前decode禁止を確認。

## 検証

- `docker compose -f server/compose.test.yml run --build --rm test python -B -m unittest discover -s tests` — 32件成功。
- `docker build -t app:ci . && docker run --rm -e PYTHONPATH=/app/src app:ci python -B -m unittest discover -s src/tests` — 306件成功、72件skip。
- app:ci mount付きAPI schema / 文書回帰 — 36件成功。
- `mypy src` / `mypy --platform win32 src` — 各79 source files成功。
- 認証・入力制限モジュールのmypy — 4 source files成功。
- `ruff check server/src server/tests` — 成功。

## 制約

資格情報台帳の永続化・発行/失効API、ASGI routeへの接続、証明書運用と実接続試験は、それぞれ後続Taskの責務。サーバー起動側は`create_server_tls_context_from_environment()`を使い、未設定時に平文へfallbackしないこと。
