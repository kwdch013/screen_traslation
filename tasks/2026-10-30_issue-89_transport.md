# Issue #89 フレーム通信層

## 実施内容

- `Transport/` にWSS frame組み立て、strictなframe/text契約検証、結果採否台帳、認証失敗を除外する上限付き指数バックオフ、接続と受信ループを追加。
- 接続先はHTTPS設定からWSS routeを構成し、端末資格情報は保護済みストアから読んでAuthorization headerへ渡す。TLS検証は標準検証を維持し、設定された場合はSHA-256指紋も照合する。
- 切断時はsession/generationと結果台帳を無効化して `ConnectionLost` を通知し、WSSだけ再接続する。sessionは自動再開せず、呼出側の明示的 `ActivateSession` を要求する。
- clientテストでbinary/text compatibility fixture、binary message境界、session-state結果fixtureを参照し、偽socketで接続・送信・再接続を確認。
- Clientテストイメージのbuild contextをリポジトリrootへ変更し、Docker build時にも `contracts/fixtures/` が利用できるようにした。
- Windows専用テストを追加し、実機で必要なTLS・切断後表示消去/明示再開始は `未実施(Windows実機が必要)` としてskip。skipを合格扱いにしない。

## 検証

- TDD: 通信実装前に `TransportTests.cs` を追加し、Client/Transport未実装のためコンパイル失敗することを確認。
- `docker compose -f client/compose.test.yml run --build --rm test dotnet test client/tests/ScreenTranslation.Client.Tests/ScreenTranslation.Client.Tests.csproj --configuration Release` — 実行済み、22 passed。
- `docker compose -f client/compose.test.yml run --rm test` — 契約fixture 4 passed。
- `docker build -t app:ci .` — 成功。
- `docker run --rm -e PYTHONPATH=/app/src app:ci python -B -m unittest discover -s src/tests` — 306 tests、OK (72 skipped)。
- `docker run --rm -e PYTHONPATH=/app/src -v "$PWD:/workspace:ro" -w /workspace app:ci python -B -m unittest discover -s src/tests` — 306 tests、OK。
- `mypy src` / `mypy --platform win32 src` — 各79 source files、問題なし。
- `ruff check --no-cache` — 全check成功。
- Windows実機のTLS/実サーバー結合試験 — 未実施（Windows実機が必要、skip）。実サーバー接続は後続Task #90。
- develop取り込みで競合解消
