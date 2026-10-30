# Issue #88 クライアント雛形・接続設定・資格情報保護保存

## 作業内容

- `ScreenTranslation.Client` にHTTPS接続先・証明書指紋の入力検証、通常設定のJSON保存、資格情報保護インターフェースと分離保存を追加。
- WPF設定画面で接続設定の保存/取消、端末tokenの独立登録を可能にし、Windows実装にDPAPI CurrentUserを使用。
- LinuxコンテナはCore/Client共通コードと契約fixtureだけをビルド・試験し、Windows固有プロジェクトはWindows CIに分離。
- 詳細は [Issue #88](https://github.com/kwdch013/screen_traslation/issues/88) と作成するPRを参照。

## 確認

- `docker compose -f client/compose.test.yml run --build --rm test`: 成功。Core 1件、Client 8件、契約fixture 4件。
- `docker build -t app:ci .`: 成功。
- `docker run --rm -e PYTHONPATH=/app/src app:ci python -B -m unittest discover -s src/tests`: 306件成功、72件skip。
- リポジトリmount回帰: 306件成功。イメージ生成済み `frontend/dist` をread-onlyで重ねて、mountによる欠落を避けて実行。
- `mypy src` / `mypy --platform win32 src`: 79 source filesで問題なし。
- `ruff check --no-cache src scripts tests/ai_gate`: 成功。
- DPAPI Windows統合テスト: **未実施 (Windows実機が必要)**。Linuxでのskipは合格扱いにしない。push後のWindows CI結果を確認する。

## 未完了

- push・PR作成後に `gh pr checks` で `windows-client` を含むCI結果を読み戻し、Issue/PRを `issue/review-required` / `pr/review-required` に遷移する。
- 独立レビュー・mergeはこのTaskでは行わない。
