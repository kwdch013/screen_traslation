# Issue #97: 非アクティブな翻訳オーバーレイと自己キャプチャ防止

## 実施内容

- Client(OS非依存): `Overlay/`に、表示状態(`TranslationOverlayState`)、result→物理座標変換(`OverlayResultMapper`)、窓ローカルDIP変換と見た目設定(`OverlayLayout`/`OverlayAppearance`)、描画先ポート(`IOverlaySurface`)、結果採否・変換・表示・fail-closedをつなぐ`TranslationOverlayController`を追加。`ResultAcceptanceTracker.TryAccept`に取得時刻を返すオーバーロードを追加(既存シグネチャは維持)。
- Windows: `Overlay/`に別トップレベルWPF窓(`WindowsOverlayWindow`)と`WindowsOverlaySurface`を追加。拡張スタイルとメッセージフックで非アクティブ・クリック透過にし、`SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)`の設定と読み戻し一致を確認できた時だけ描画する。
- 仕様: 取得から5秒で失効、停止/再選択/対象消失/切断/除外失敗は同期的に消去、以後の旧結果は`Activate`まで拒否。位置不明(`rect: null`)は下端の「位置不明」行へ表示。
- 文書: development.md対応表、testing.mdに試験区分とOwner実機手順(未実施)を追記。

## 対応要件

REQ-F-005 / REQ-F-006 / REQ-F-007 / REQ-NF-008（ACC-02 / ACC-04 / ACC-07）

## 範囲外・未実施

- Windows実機での自己混入(WGC/DXGI/GDI)、クリック透過の実操作、見た目、混在DPI・複数モニターは未実施(#135/#136)。
- `MainWindow`への配線(開始前の`Prepare`必須化、タイマーでの`Tick`)は設定画面・履歴の#98。
- Captureディレクトリは#179と競合させないため未変更。

## 試験結果

- `docker compose -p t97 -f client/compose.test.yml run --build --rm test`: Core 1件、Client 173件、接続・取得結合24件、Contracts 4件すべて成功。
- Windowsターゲット(`ScreenTranslation.Windows.Tests`、`Category=Overlay`を含む)のビルドをLinux SDKコンテナで確認(0 error)。実行はWindows runner(`windows-client` CI)。
- 文書整合(`test_v1_documentation`/`test_web_documentation`/`test_desktop_removal`): 45件成功。`app:ci`相当の全体回帰: 310件成功、76 skip。
- Mutation(14件、Client.Testsで全て検出): 期限境界(`>`→`>=`を状態とPresent両方)、世代検査除去、Clearでactive維持、未来取得時刻の許容、古い取得の許容、画像寸法検査除去、画像外領域検査除去、ROI原点加算除去、除外再確認除去、Prepare未実施でのBegin許可、空スナップショットで非表示にしない、DIP変換の原点ずれ、見た目の範囲クランプ除去。
- 実機(自己混入・クリック透過の実操作・混在DPI・見た目): **未実施**。
