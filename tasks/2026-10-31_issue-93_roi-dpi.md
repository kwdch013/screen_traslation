# Issue #93: ROI選択と混在DPI・モニター間の座標変換

## 実施内容

- Client Geometryに物理px・モニター相対論理px・ROI画像px間の変換、Per-Monitor DPI context、負座標、半開区間、0から遠ざける最近傍丸めを実装。
- 契約fixtureをC#から読み、変換とモニター包含の期待値を検証。
- `RegionSelection`に64×32～1920×1080・最大2,073,600画素、単一モニターへの完全包含、キャンセル、DPI context更新時の選択無効化/世代進行を実装。
- WindowsにPer-Monitor V2 manifest、物理モニター/DPIカタログ、モニター単位のドラッグ選択オーバーレイ、Esc取消、DPI通知時の選択中断を追加。
- `ScreenTranslation.Windows.Tests`へ専用の新規テストファイルだけを追加。共有 `.csproj` は変更していない。
- 開発対応表へIssue成果物・要件ID・未実施の実機確認範囲を追記。

## 設計・契約

- `contracts/coordinates.md`、`contracts/fixtures/geometry/coordinate-cases.json`
- `src/app/dpi_coordinates.py`、`docs/v1.0/research/mixed-dpi.md`
- `docs/v1.0/design/architecture.md`、`requirements/version_1/requirements.md`
- 対応要件: REQ-F-002、REQ-F-005、REQ-NF-008（ACC-06/07）

## 試験結果

- TDD Red: 未実装のGeometry/RegionSelection APIを参照するテストを追加し、コンテナのクリーンビルドで失敗することを確認。
- Client compose (`docker compose -p issue-93 -f client/compose.test.yml run --build --rm test`): Core 1件、Client 51件、Contracts 4件成功。
- Windows target: `ScreenTranslation.Windows.Tests.csproj` と参照WPFアプリのWindowsターゲットビルド成功（0 error、既存 `TransportPlatformTests.cs` のxUnit analyzer warning 1件）。Linuxには `Microsoft.WindowsDesktop.App` runtimeがないためWindows.Tests実行は未実施。Windows runnerで実行する。
- Python 3.14コンテナ通常回帰: 308件、74 skipで成功。`src/`をread-only mountした回帰: 308件成功。
- 開発文書検査: `test_v1_documentation` / `test_web_documentation` 39件成功。development.md対応表の要件IDがrequirementsに定義されていることを含む。
- `mypy src` と `mypy --platform win32 src`: 各79 source files成功。`ruff check --no-cache src scripts tests/ai_gate`: 成功。
- Mutation: 丸めを一時的にToEvenへ変更したテストで正負の半端値2件が失敗することを確認し、コードを元に戻した。
- 実機での混在DPI誤差2 px以下と実際のROI選択操作: **未実施(Windows実機が必要、後続 #136/#148系)**。

## 変更範囲

- `client/src/ScreenTranslation.Client/Geometry/`
- `client/src/ScreenTranslation.Client/Capture/RegionSelection.cs`
- `client/src/ScreenTranslation.Windows/Capture/`
- `client/src/ScreenTranslation.Windows/MainWindow.xaml*`、`app.manifest`
- `client/tests/ScreenTranslation.Client.Tests/`
- `client/tests/ScreenTranslation.Windows.Tests/WindowsMonitorCatalogTests.cs`
- `docs/v1.0/development.md`
- `tasks/2026-10-31_issue-93_roi-dpi.md`
