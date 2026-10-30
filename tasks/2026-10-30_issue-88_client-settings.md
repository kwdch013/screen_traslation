# Issue #88 クライアント雛形・接続設定・資格情報保護保存

## 作業内容

- `ScreenTranslation.Client` にHTTPS接続先・証明書指紋の入力検証、通常設定のJSON保存、資格情報保護インターフェースと分離保存を追加。
- WPF設定画面と設定モデル、端末tokenの分離保存を追加し、Windows実装にDPAPI CurrentUserを使用。
- LinuxコンテナはCore/Client共通コードと契約fixtureだけをビルド・試験し、Windows固有プロジェクトはWindows CIに分離。
- 詳細は [Issue #88](https://github.com/kwdch013/screen_traslation/issues/88) と作成するPRを参照。

## 確認

- `docker compose -f client/compose.test.yml run --build --rm test`: 成功。Core 1件、Client 9件、契約fixture 4件。
- `docker build -t app:ci .`: 成功。
- `docker run --rm -e PYTHONPATH=/app/src app:ci python -B -m unittest discover -s src/tests`: 306件成功、72件skip。
- リポジトリmount回帰: 306件成功。イメージ生成済み `frontend/dist` をread-onlyで重ねて、mountによる欠落を避けて実行。
- `mypy src` / `mypy --platform win32 src`: 79 source filesで問題なし。
- `ruff check --no-cache src scripts tests/ai_gate`: 成功。
- DPAPI保護/復号と改ざん検出: [Windows CI `windows-client` 成功](https://github.com/kwdch013/screen_traslation/actions/runs/41137230257)。改ざんしたDPAPIデータが拒否されることを確認。
- 設定保存データの改ざん検出: 認証タグ付きテストprotectorで保存bytesを破損させ、`LoadAsync` が `InvalidDataException` で拒否することを確認。復号を一時的に迂回するとテストが失敗することも確認。

## 未完了

- **未実施はWPF画面での起動・設定保存/再読込/取消のWindows実機操作のみ**。手順・結果記録テンプレートを含む独立Task [#148](https://github.com/kwdch013/screen_traslation/issues/148)で実施する。DPAPIテストはWindows CIで実行済みであり、実機画面操作とは区別する。
- 独立レビュー・mergeはこのTaskでは行わない。
