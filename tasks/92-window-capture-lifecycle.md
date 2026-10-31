# Issue #92: ウィンドウ・画面選択とキャプチャライフサイクル

## 実施内容

- Client に対象モデル・対象列挙/セッションの抽象化とライフサイクル制御を追加。
- 選択は明示開始を起動せず、開始失敗・停止・再選択・対象消失・最小化・DPI変更・取得拒否で世代を無効化して停止する。
- 停止/無効化時は世代通知を先に発行し、キャプチャ資源は停止後に必ず破棄する。
- Windows 側で可視かつ非最小化の外部ウィンドウとモニター、物理境界、DPIを列挙する。
- Windows側に `WindowsCaptureSessionFactory` と WGC (`GraphicsCaptureItem` / `Direct3D11CaptureFramePool` / `GraphicsCaptureSession`) のsession実装を追加。frame到着を取り出し、対象終了・frame取得失敗で失効イベントを発行する。
- `WindowsCaptureRuntime` からWindows対象catalogと `CaptureLifecycleController` を組み立てる。controllerはsession失効イベントを停止へ接続する。
- WinEventでウィンドウ破棄・最小化・位置/DPI変化を監視し、ディスプレイは一覧の境界/DPIを定期比較する。
- Linuxテストはfake sessionで状態遷移・失効通知・Stop/Dispose双方の例外・Dispose一回を検証する。

## 設計・契約

- `docs/v1.0/design/architecture.md`、`security.md`、ADR-0002 windows-client。
- `contracts/session-state.md`: 明示開始、stop/target変更時の即時無効化、停止後の暗黙再開禁止。
- `contracts/coordinates.md`: 仮想デスクトップ物理座標、負座標を保持。
- `docs/v1.0/research/capture-exclusion.md`、`mixed-dpi.md`。

## 試験結果

- TDD Red: 新規テストが未実装の `ScreenTranslation.Client.Capture` を参照してコンパイル失敗。
- Linuxコンテナ: `CaptureLifecycleTests` 11件成功を含むClient 20件成功 (fake session)。
- Client compose: Core 1件、Client 20件、Contract 4件成功。
- Windows-targeted build: `ScreenTranslation.Windows.Tests.csproj` 成功、0 warning / 0 error。Windows desktop runtimeがないLinuxコンテナではWindows.Testsの実行はできないため、実行結果はWindows CIで確認する。
- Python 3.14: 通常回帰と`src/`のみを`/app/src`へmountした回帰が各306件成功 (72 skip)。
- 静的検査: `mypy src`、`mypy --platform win32 src` (各79 source files)、`ruff check src` 成功。
- Linux上でのWindows列挙テスト実行: **skip** (理由: HWND/モニター列挙にはWindows APIが必要)。Windows CIでテストを実行する。
- WGC実画面取得の成否/frame内容、自己キャプチャ除外と `SetWindowDisplayAffinity`、混在DPIの実測: **未実施(対応Windows実機が必要)**。skipを合格扱いにしない。実機確認は #135/#136/#148 系Taskで行う。

## 変更範囲

- `client/src/ScreenTranslation.Client/Capture/`
- `client/tests/ScreenTranslation.Client.Tests/CaptureLifecycleTests.cs`
- `client/src/ScreenTranslation.Windows/Capture/`
- `client/tests/ScreenTranslation.Windows.Tests/`
- `tasks/92-window-capture-lifecycle.md`
- `docs/v1.0/design/architecture.md`
- `plan/version_1/roadmap.md`
