# Issue #93: ROI選択と混在DPI・モニター間の座標変換

## 実施内容

- Client Geometryに物理px・モニター相対論理px・ROI画像px間の変換、Per-Monitor DPI context、負座標、半開区間、0から遠ざける最近傍丸めを実装。
- 契約fixtureをC#から読み、変換とモニター包含の期待値を検証。
- `RegionSelection`に64×32～1920×1080・最大2,073,600画素、単一モニターへの完全包含、キャンセル、DPI context更新時の選択無効化/世代進行を実装。
- WindowsにPer-Monitor V2 manifest、物理モニター/DPIカタログ、モニター単位のドラッグ選択オーバーレイ、Esc取消、DPI通知時の選択中断を追加。
- `ScreenTranslation.Windows.Tests`へ専用の新規テストファイルだけを追加。共有 `.csproj` は変更していない。
- 開発対応表へIssue成果物・要件ID・未実施の実機確認範囲を追記。
- PR #164 の変更要求に対応し、`GetDpiForMonitor`を除去。Microsoft Learnは同APIをper-monitor DPI-aware threadで使用しないよう明記し、デスクトップアプリには`GetDpiForWindow`を推奨しているため、各モニター矩形の中央にPMv2一時HWNDを作成してDPIを取得する注入可能な`IMonitorDpiProvider`を追加。
- 選択sessionを純粋なClient状態機械へ分離。各overlayは物理配置完了前の`WM_DPICHANGED`を無視し、ユーザー選択開始後の`WM_DPICHANGED`/`WM_DISPLAYCHANGE`は`OperationCanceledException`で通知する。Escは従来どおり`null`結果。

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
- Microsoft Learn API根拠: [GetDpiForMonitor](https://learn.microsoft.com/en-us/windows/win32/api/shellscalingapi/nf-shellscalingapi-getdpiformonitor) はPMv2呼び出しスレッドでは使わないよう明記し、[GetDpiForWindow](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getdpiforwindow) はPM-aware windowに対し配置先モニターDPIを返す。デスクトップアプリでの推奨は[DPI and device-independent pixels](https://learn.microsoft.com/en-us/windows/win32/learnwin32/dpi-and-device-independent-pixels)に記載。
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

## PR #164 変更要求への対応と再確認

- Microsoft Learn: [GetDpiForMonitor](https://learn.microsoft.com/en-us/windows/win32/api/shellscalingapi/nf-shellscalingapi-getdpiformonitor) はper-monitor DPI-aware threadで使用しないよう明記。[GetDpiForWindow](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getdpiforwindow) はPM-aware windowの配置先モニターDPIを返し、[デスクトップアプリ向けDPI資料](https://learn.microsoft.com/en-us/windows/win32/learnwin32/dpi-and-device-independent-pixels)もこのAPIを推奨するため採用。
- `docker compose -p issue-93 -f client/compose.test.yml run --build --rm test`: Core 1件、Client 57件、Contracts 4件成功。Clientには初回配置/通知時の状態遷移、Escと無効化の区別、fake `IMonitorDpiProvider`を使った96/120/144/192 DPIの物理ROI確認を含む。
- Mutation: 初回配置通知を無効化、Esc結果を無効化へ統合、表示DPI providerを96固定、の各変更で対象Clientテストが失敗。mutationは戻し、最終の同コマンドは57件成功。
- `docker build -t app:ci .`後の通常回帰と`src/` read-only mount回帰: 各308件成功（74 skip）。mount付き`test_v1_documentation`/`test_web_documentation`: 39件成功、対応表の要件ID検査を含む。
- `mypy src` / `mypy --platform win32 src`: 各79ファイル成功。`ruff check --no-cache src scripts tests/ai_gate`: 成功。
- Linux SDK containerで`dotnet build ScreenTranslation.sln --configuration Release -p:EnableWindowsTargeting=true`: 0 error。既存`TransportPlatformTests.cs`のxUnit analyzer warning 1件。Windows.Testsの実行はWindows runtimeが必要なためWindows CIで確認する。
- 混在DPI実機でのROI選択操作と物理誤差2 px以下の実測: **未実施（Windows実機が必要、#136/#148系）**。

## PR #164 追加変更要求 (high) の対応

- `RegionSelectionResultMapper`をWindows依存のないClient純粋ロジックへ追加し、状態から`TaskCompletionSource<Rect2D?>`の完了結果へ変換。Windows overlayはsession状態と選択ROIをmapperへ渡すだけで、TCSの結果/例外分岐を持たない。MainWindowの`OperationCanceledException`契約により環境無効化メッセージへ到達し、Escの`null`表示と分かれる。
- Linux ClientテストでSelected=ROI、Cancelled(Esc)=`null`、Invalidated= `OperationCanceledException`を確認。CancelledとInvalidatedを区別し、例外型と無効化メッセージを固定。
- Mutation確認 (各回 `docker compose -p issue-93 -f client/compose.test.yml run --build --rm test` で新規 Client テスト60件を実行):

| Mutation | 結果 | 検出 |
| --- | --- | --- |
| mapperでInvalidatedを`TrySetResult(null)`に統合 | 失敗 (59 passed / 1 failed) | Invalidated例外契約テストが「例外なし」で失敗 |
| mapperのTCS結果反映を`TrySetResult(null)`固定（Selected/Invalidated） | 失敗 (58 passed / 2 failed) | Selected ROI契約とInvalidated例外契約で失敗 |

- いずれのmutationも直ちに復元。Windows固有の画面通知・WPF操作を含む実機確認は**未実施（Windows実機が必要、#136/#148系）**。
