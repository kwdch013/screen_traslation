# v1.0 サーバー試験

## C#クライアント試験

OS非依存のCore・Clientロジックと契約fixtureは.NET 10 SDKコンテナ内で実行します。通常のアプリイメージの`src/tests`はこの追加試験の影響を受けません。

```bash
docker compose -f client/compose.test.yml run --build --rm test
```

Windowsの`windows-client` CIは`client/ScreenTranslation.sln`全体をビルド・実行します。`ScreenTranslation.Client.IntegrationTests`ではKestrelの契約準拠モックをloopbackに起動し、試験ごとに一時CA/サーバー証明書を生成して実TLS/WSS接続します。OSの信頼ストアは変更しません(非対話のCIでダイアログ待ちになりブロックするため)。試験側の証明書検証で、試験ごとに生成した一時CAを`X509Chain`のCustomRootTrustとしてのみ信頼します。サーバー証明書はPFX経由(`UserKeySet | Exportable`、`PersistKeySet`は使わない)で読み込み、試験終了時に破棄します。固定ホスト/IP・秘密鍵・実資格情報はソースやfixtureへ保存しません。

```powershell
dotnet test client/tests/ScreenTranslation.Client.IntegrationTests/ScreenTranslation.Client.IntegrationTests.csproj --configuration Release --filter Category=ConnectionIntegration
```

接続・フレーム送信、401/403/409の認証/所有権拒否、503 `MODEL_NOT_READY`、HTTP protocol拒否、WSS切断後の再接続、期限切れ・SANなし・未信頼CAの証明書拒否、取消後に届く遅延応答の無視を確認します。通信の開始/完了は`TaskCompletionSource`と取消tokenで同期します。30秒のtimeoutはハング時のwatchdog専用であり、合否の時間条件には使いません。通信層の自動再接続だけではsessionを再開しないことも既存のClient単体試験で確認します。

WPF画面での設定変更中の接続取消、ウィンドウ終了後の遅延UI更新なし、終了中の再接続なしはOwner実機手順に記録します。手順: (1) サーバー応答を保留した状態で接続先を変更して保存し、旧接続の遅延完了が新しい状態表示を上書きしないことを確認、(2) 接続を取消した直後に旧サーバーから応答させ、状態表示とsocket数が増えないことを確認、(3) 再接続待ち中にウィンドウを閉じ、閉じた後のUI更新/再接続がなくsocketが解放されることを確認、(4) TLS・認証・MODEL_NOT_READY・切断・再接続停止時の日本語状態と復旧案内を確認。担当: Owner。結果: **未実施(Windows実機が必要)**。混在DPI/負座標は #136 系、キャプチャ除外と実画面取得は #135/#148 系の実機Taskで確認します。実Windows/Linux間通信・サーバー実処理を含むE2Eは #108 等で行います。この未実施項目をCI成功やTask合格として数えません。

2026-10-31にLinux .NET SDKコンテナでCore 1件・Client 70件・接続結合12件・Contracts 4件を実行し、すべて成功しました。CPU負荷をかけた同一試験の3反復も成功しました。WPF実機確認とWindows hosted runnerの結果は別扱いにし、手動項目を合格に含めません。実行詳細とmutation確認は[Issue #90作業記録](../../tasks/2026-10-31_issue-90_connection-windows-tests.md)を参照してください。

## 実キャプチャから送信までの結合試験 (Issue #95)

`CaptureSendPipeline`(`client/src/ScreenTranslation.Client/Capture/`)が、取得フレーム→ROI切り出し→変化判定→PNG符号化→最新優先送信を接続します。世代切替・停止・送信失敗では変化判定の基準(`FrameProcessor.ResetBaseline`)を捨て、送られなかった画素が「無変化」と判定されて二度と送られない状態を防ぎます。取得時の世代が現在と異なるフレームは処理せず、sessionが無い間も何も送りません。

| 区分 | 場所・分類 | 実行環境 | 内容 |
| --- | --- | --- | --- |
| OS非依存の連鎖 | `client/tests/ScreenTranslation.Client.IntegrationTests/CaptureTests.cs` (`Category=CaptureSendIntegration`) | .NET SDKコンテナ(`client/compose.test.yml`に含む) | 負座標を含む96/144/192 DPIの仮想デスクトップで、論理座標から変換した物理ROIの画素が受信PNGと1対1で一致(契約の許容誤差2 physical px以内かつ実際は0)。再選択で待機中の旧領域画像が送られず、旧世代フレームは拒否され、通信中の送信が取り消される。対象終了/最小化/取得拒否/DPI変更で送信が止まり取得sessionが破棄される。送信失敗後に同一画素が再送対象になる。20回の再選択でsessionが全て1回だけ停止・破棄される |
| 配線の単体 | `client/tests/ScreenTranslation.Client.Tests/CaptureSendPipelineTests.cs` | 同上 | 基準リセット、旧世代拒否、session無し拒否、送信失敗と呼び出し側取消の区別 |
| Win32実取得 | `client/tests/ScreenTranslation.Windows.Tests/CaptureIntegrationTests.cs` (`Category=CaptureIntegration`) | Windowsのみ(`windows-client` CI) | 座標を画素値にした試験ウィンドウをWin32 `PrintWindow`で実際に取得し、ROIと受信画像が1対1で一致すること、取得対象の終了後は取得不可で旧画像が送られないこと、再選択後は新領域だけが送られることを確認 |
| WGC実取得 (Issue #179) | `client/tests/ScreenTranslation.Windows.Tests/WgcCaptureIntegrationTests.cs` (`Category=CaptureIntegration`) | Windowsのみ(`windows-client` CI) | 専用スレッドでメッセージループを回す既知パターンのウィンドウをWindows Graphics Captureで取得し、`FrameArrived`から読み出した画素がROIどおり(0 px誤差)に`CapturedFrame`→PNG→送信まで届くこと、ROI未選択ならGPU面を読み出さないこと、開始/停止を25回反復してもプロセスのハンドル数が増え続けず停止後にフレームが届かないこと、対象ウィンドウを閉じるとTargetUnavailableで無効化されることを確認 |
| WGC画素の変換 (Issue #179) | `client/tests/ScreenTranslation.Client.Tests/BgraFrameConverterTests.cs`・`CaptureFrameRouterTests.cs` | .NET SDKコンテナ | 行詰め(stride)付きBGRAの詰め直し、開始位置、内容サイズでの切り出し、元バッファの複製、不正寸法の拒否と例外メッセージへ画素値を含めないこと。ROI・世代を画素の読み出し前に採取して旧世代フレームを拒否すること |

```bash
docker compose -f client/compose.test.yml run --build --rm test
```

```powershell
dotnet test client/tests/ScreenTranslation.Windows.Tests/ScreenTranslation.Windows.Tests.csproj --configuration Release --filter Category=CaptureIntegration
```

CaptureIntegrationはWindows専用で、Linuxでは対象プロジェクトがビルドされません。Linuxでのskipをこの試験の合格として扱いません。`CaptureIntegrationTests`はWin32 `PrintWindow`、`WgcCaptureIntegrationTests`はWGCで取得した画素を使います。

### WGC画素読み出しの設計と制約 (Issue #179)

- `WindowsCaptureSession.OnFrameArrived`(`client/src/ScreenTranslation.Windows/Capture/`)は、ROIと世代を**画素の読み出し前に**`ICapturedFrameSink.TryBeginFrame`から採取します。ROI未選択(null)ならGPU面を読み出しません。読み出し中に再選択されても旧世代のまま渡され、`CaptureSendPipeline`が`StaleGeneration`として拒否します。
- 読み出しは`WgcFrameReader`が`SoftwareBitmap.CreateCopyFromSurfaceAsync`でBGRA8へ複製し、`BgraFrameConverter`が行詰めを除いた`CapturedFrame`(stride=幅×4、内容サイズで切り出し)へ変換します。フレーム・GPU面・SoftwareBitmap・読み出しバッファはフレームごとに解放します。停止(`StopAsync`)と破棄(`DisposeAsync`)の両方でフレームプール・取得session・D3Dデバイス・取得対象を解放します(反復しても二重解放しない)。
- 読み出しや受け渡しが失敗した場合は、例外の内容を捨てて`CaptureDenied`で無効化し取得を止めます。画像データはログにも例外メッセージにも出しません。取得除外・保護コンテンツなどでWGCが使えない場合に、`PrintWindow`や画面複製などの別方式へ無断でフォールバックしません。D3Dデバイスだけは、GPUが無い環境でソフトウェア描画(WARP)へ切り替えます(取得方式はWGCのまま)。
- WGCは`WS_EX_NOACTIVATE`のウィンドウを取得対象にできません(CIで`E_INVALIDARG`を確認)。取得対象のWinRTオブジェクトは`MarshalInspectable.FromAbi`で変換します(COMのRCWへ直接キャストすると`InvalidCastException`)。
- 対象終了などの無効化は`WindowsCaptureTargetWatcher`のWinEventフックで検出します。アウトオブコンテキストのフックは設定したスレッドがメッセージを処理しないとコールバックが届かないため、`StartAsync`はUIスレッド(メッセージループあり)から呼びます。CIの対象終了試験ではメッセージ処理スレッド(`PumpingThread`)で開始し、WGCのClosedイベントの到着には依存しません(最初の30秒タイムアウトの原因は、メッセージを処理しないスレッドで開始していたこと)。
- マウスカーソルは翻訳対象の画像へ含めません(`IsCursorCaptureEnabled=false`)。対象のサイズが変わったらフレームプールを作り直し、以降のフレームは新しい内容サイズで届きます(ROIが範囲外になれば`Rejected`で再選択を案内)。
- アプリ全体の配線(`CaptureFrameRouter`と`CaptureLifecycleController`の接続、取得fps上限に合わせた読み出しの間引き)はIssue #180で`TranslationSessionHost`に実装しました(下の「アプリ構成の配線」)。`WindowsCaptureSessionFactory`は`ICapturedFrameSink`を指定した場合だけ画素を読み出します。
- Issue #180で読み出しのコピーを削減しました。`CopyToBuffer`の書き込み先を管理配列(`AsBuffer`)にしてWinRTの`Buffer`と`DataReader`経由の2回の複製をなくし(`Buffer`を作らないため破棄漏れも起きない)、行詰めなしなら`BgraFrameConverter.ToCapturedFrameOwned`が配列をそのまま`CapturedFrame`にします(内容サイズが面より小さい等で詰め直しが要るときだけ複製)。削減量の実測は未実施です(実GPUのOwner実機手順で記録)。

### Owner実機手順 (混在DPI・複数モニター・画面表示)

hosted runnerで再現できない項目です。担当: Owner。**結果: 未実施(Windows実機が必要)**。実施した場合は日付、Windows版、モニター構成(解像度・DPI・配置)、合否をIssueへ記録し、この欄を更新してください。

1. 倍率が異なる2台以上のモニター(例: 100%と150%)、および主モニターより左/上に置いた(負座標の)モニターを用意する。
2. 各モニターの既知の目盛り/文字を持つウィンドウでROIを選択し、取得開始する。受信側(またはサーバーログの画像寸法)でROI寸法が選択した物理pxと一致し、目盛り位置のずれが2 physical px以下であることを確認する。
3. 取得中に対象ウィンドウを閉じる/最小化する/別モニターへ移動してDPIを変える/取得権限を拒否する。送信が止まり、旧領域の画像がそれ以降送られず、取得sessionが解放される(再開始まで送信されない)ことを確認する。
4. 負荷(別プロセスでCPUを飽和)をかけた状態でROIを再選択し、再選択前の領域の画像が受信されないことを確認する。
5. 取得除外(自己キャプチャ除外/WDA)が失敗した場合に送信が停止することを確認する(#135/#136系)。

### Owner実機手順 (WGCの実GPU取得・Issue #179)

hosted runnerのソフトウェア描画(GPUなし)ではなく実GPUと実際の画面で確認する項目です。担当: Owner。**結果: 未実施(Windows実機が必要)**。実施した場合は日付、Windows版、GPU、モニター構成(解像度・DPI・配置)、合否をIssueへ記録し、この欄を更新してください。CI成功をこの項目の実施として数えません。

1. 実GPUのWindows 10 2004以降/Windows 11で、座標目盛りを持つウィンドウをWGCで取得し、ROI寸法・目盛り位置が選択した物理pxと一致する(ずれ2 physical px以下)ことを確認する。
2. 4Kや100%/150%など倍率の異なるモニターで、ウィンドウをモニター間で移動したときに送信が止まり(DPI変更)、再選択後は新しい物理pxのROIで送られることを確認する。
3. 取得開始/停止/対象変更を100回以上反復し、タスクマネージャー(またはPerfMon)でプロセスのハンドル数とGPU専用メモリが増え続けないことを確認する。
4. 画面取得から除外されたウィンドウ(WDA_EXCLUDEFROMCAPTURE)や保護コンテンツ(DRM動画等)を対象にして、別方式へ切り替わらず、取得できない/黒画像を送らない動作になるか確認し、結果を#135の記録へ追記する(黒画像の検出は現状未実装のため、結果によりTaskを追加する)。
5. ウィンドウをリサイズしたとき、フレームが新しいサイズで届きROIの範囲外判定が再選択案内になることを確認する。

## アプリ構成の配線 (Issue #180)

`TranslationSessionHost`(`client/src/ScreenTranslation.Client/App/`)が、`CaptureLifecycleController`・`CaptureFrameRouter`・`CaptureSendPipeline`(`FrameProcessor`/`FrameSender`)・WSS接続(`StreamTransportClient`、抽象は`ITranslationTransport`)・`TranslationOverlayController`を組み立て、UIから呼ぶ操作(`ConnectAsync`・`SelectTargetAsync`・`SelectRegion`・`StartAsync`・`StopAsync`)を提供します。Windowsでは`WindowsCaptureRuntime.CreateSessionHost`が実WGCの工場を渡して組み立てます。開始/停止ボタン・ホットキー・履歴・設定画面は#98/#99で、これらのAPIを呼びます。

| 項目 | 振る舞い |
| --- | --- |
| 開始前のPrepare必須 (fail-closed) | `StartAsync`は`TranslationOverlayController.Prepare`でキャプチャ除外を確認できるまで`OverlayUnavailable`を返し、取得セッションを作らず、`ActivateSession`も呼ばず、画像を送らない。取得スレッドの読み出し判定も`CanStream`がfalseなら経路を返さない |
| 失効のタイマー配線 | ホストが失効確認ループを持ち、次の失効時刻(最大250ms間隔)ごとに`Tick`を呼ぶ。取得から5秒を超えた表示は製品経路で消える |
| 停止・再選択・対象消失・切断・除外失敗・送信失敗 | 世代無効化(`GenerationInvalidated`)・切断(`ConnectionLost`)・除外失敗(`FailedClosed`)・送信例外を受けた同期処理で、取得経路の遮断→待機画像と通信中の送信の破棄と変化判定の基準破棄(`ResetBaseline`)→表示消去を行ってから、取得セッションの停止・解放が進む(停止完了を待たずに旧領域は送られず、表示は消える)。理由は`SessionEnded`で通知 |
| 世代 | 開始・ROI再選択ごとに世代を1進め、`FrameSender`・`StreamTransportClient`・結果採否・オーバーレイへ同じ値を渡す。ROI再選択は旧画像・通信中の送信・表示を破棄してから新ROIの世代2以降で送る。旧世代フレームは送信直前の照合でも取り下げる |
| 取得fpsの間引き | `CaptureFrameRouter.TryBeginFrame`が、取得fps上限で破棄される見込みのフレームはGPU→CPUの読み出し前にnullを返す(読み出しコストを払わない) |
| 停止後の1フレーム | `WindowsCaptureSession`が配信直前に停止を再確認する。残る隙間はホストが先に`pipeline.EndSession`しているため`NoSession`/`StaleGeneration`で拒否される |
| 解放・並行 | `DisposeAsync`は冪等で並行呼び出しも同じ完了を待つ(`WindowsCaptureRuntime`との二重破棄でも例外にならない)。停止は取得セッションの停止(操作ロック待ち)より先に送信と表示を止める。`ConnectAsync`を2回呼んでも受信ループは1本、`StartAsync`は直列化されPrepareは1回。送信ループの失敗は、そのループ自身が現在のセッションのときだけセッションを止める(停止→即再開の窓で新セッションを止めない)。ループが止まらなくても解放は`ShutdownTimeout`(既定10秒)で先へ進む |
| 切断後の再開 | 切断・送信失敗後は自動では送信を再開しない。利用者の明示操作(`StartAsync`)まで待つ |
| 例外内容 | `Faulted`には画像・訳文・session_idを含めない固定文言だけを渡す |

| 区分 | 場所・分類 | 実行環境 | 内容 |
| --- | --- | --- | --- |
| 構成の単体 | `client/tests/ScreenTranslation.Client.Tests/TranslationSessionHostTests.cs`(`HostFixture.cs`、共有代替`client/tests/Shared/AppHostTestSupport.cs`) | .NET SDKコンテナ | Prepare失敗時に取得セッションを作らない、前提不足の結果、ROIの物理座標への変換と画素一致、fps間引き、停止中に取得停止が未完でも表示が消え経路が遮断される、停止後に届く旧フレームの拒否、停止→再開で同一画像を再送(基準破棄)、再選択後は世代2・frame_id 1・新寸法だけが送られる、対象消失、切断、送信失敗、5秒失効のTick、表示中の除外喪失、破棄。注入クロックと手動ティッカーで固定sleepに依存しない |
| 組み立て済みの結合 | `client/tests/ScreenTranslation.Client.IntegrationTests/AppWiringTests.cs`(`Category=CaptureSendIntegration`) | 同上 | 実`StreamTransportClient`・実PNG符号化・実オーバーレイ制御・実ライフサイクルを通し、ROI選択→(負座標の物理ROI左上が先頭画素の)WSSバイナリ送信→resultの表示→再選択でのオーバーレイ消去と世代2以降の送信→停止と表示消去、および切断で表示消去・取得解放・利用者通知を確認 |
| Windows構成 | `client/tests/ScreenTranslation.Windows.Tests/WindowsCaptureSessionFactoryTests.cs` | Windowsのみ(`windows-client` CI) | `WindowsCaptureRuntime.CreateSessionHost`が実WGC工場でホストを組み立て、対象未選択ではPrepareも呼ばないこと |

**未実施(Owner実機手順)**: 実WGC・実HWND(WDA)・実WSSサーバーを通した通し(ROI選択→実画面取得→送信→サーバー結果の重畳→再選択/停止/切断で1秒以内に表示が消える)、混在DPI・複数モニター、実GPUでの読み出しコスト削減量の計測。結果は**未実施**で、CI成功をこれらの実施として数えません。手順は上の「Owner実機手順」に、通しとして次を加えます。

1. 実サーバーへ接続し、ウィンドウまたはモニターとROIを選び、開始する(開始前にオーバーレイのキャプチャ除外が確認できないと開始されないこと)。
2. 訳文が重畳され、取得から5秒たつと消えることを確認する。
3. 再選択・停止・対象ウィンドウを閉じる・ネットワークを切断のそれぞれで、訳文が1秒以内に消え、旧領域の画像が送られないこと、切断後は自動で送信が再開されないことを確認する。

## 翻訳オーバーレイと自己キャプチャ防止 (Issue #97)

訳文は対象アプリとは別のトップレベルWPF窓に描きます。窓はフォーカスもクリックも受け取らず、`SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)`の設定と読み戻しの一致を確認できた場合だけ描画します。確認できなければ描かず、`FailedClosed`で理由を通知し、`CanStream`がfalseのままになります(呼び出し側は画像送信を始めない)。

| 区分 | 場所・分類 | 実行環境 | 内容 |
| --- | --- | --- | --- |
| OS非依存の状態・変換 | `client/tests/ScreenTranslation.Client.Tests/Overlay*Tests.cs` | .NET SDKコンテナ(`client/compose.test.yml`に含む) | 注入クロックで、取得から5秒ちょうどまで表示し超過で失効、より古い取得・旧generation・非アクティブ・未来の取得時刻の拒否、停止/再選択/対象消失/切断/除外失敗での同期消去と以後の遅延結果の拒否、空結果での消去、画像寸法がROIと異なる結果と画像外領域の破棄、負座標ROIでの物理座標復元、96/144/192 DPIでの窓ローカルDIP変換、除外失敗時の描画禁止、訳文本文を`ToString`へ出さないこと |
| 実HWNDの検査 | `client/tests/ScreenTranslation.Windows.Tests/OverlayWindowsTests.cs` (`Category=Overlay`) | Windowsのみ(`windows-client` CI) | 拡張スタイル(NOACTIVATE/TRANSPARENT/TOOLWINDOW/LAYERED)、`WM_NCHITTEST`=HTTRANSPARENTと`WM_MOUSEACTIVATE`=MA_NOACTIVATE、表示してもフォアグラウンドにならないこと、除外設定失敗・読み戻し不一致では描画されないこと、実APIの結果が「除外を確認できて表示」または「失敗して非表示」のどちらかに一致すること |

```bash
docker compose -f client/compose.test.yml run --build --rm test
```

```powershell
dotnet test client/tests/ScreenTranslation.Windows.Tests/ScreenTranslation.Windows.Tests.csproj --configuration Release --filter Category=Overlay
```

`Category=Overlay`はWindows専用で、Linuxでのskipを合格として扱いません。この試験は実際のWGC/DXGI/GDIから窓が写らないことを検証しません(WDAの設定成功は各取得経路からの除外を保証しない。[調査](research/capture-exclusion.md))。

### Owner実機手順 (オーバーレイ)

hosted runnerで再現できない項目です。担当: Owner。**結果: 未実施(Windows実機が必要。実測は #135 / #136)**。実施した場合は日付、Windows版、モニター構成、合否をIssueへ記録し、この欄を更新してください。

1. 対象アプリ(テキスト入力できるウィンドウ)を前面にし、取得を開始して訳文を表示する。対象の入力欄でキー入力でき、キャレットとフォーカスが移らず、訳文の上をクリック/ドラッグしても対象が操作できる(クリックが透過する)ことを確認する。
2. 表示中の訳文が、取得した画像(サーバーログの画像またはデバッグ保存画像)に写っていないことを、WGC・DXGI・GDIそれぞれで3回以上確認する。1回でも写った場合は「除外不成立」とし、送信が止まり理由が表示されることを確認する。
3. 100% / 150% / 200%のモニターへ対象を移動し、訳文が対応する領域に重なること(四隅の物理px誤差2以下)と、文字の大きさ・折り返し・透明度・「位置不明」行の見た目が読めることを確認する。負座標のモニターでも確認する。
4. 停止・再選択・対象ウィンドウを閉じる・サーバーを停止して切断、のそれぞれで訳文が1秒以内に消えること、取得から5秒たつと自然に消えること、停止後に遅れて届いた結果で再表示されないことを確認する。
5. 除外を確認できない状態(別の取得ツールの常駐や古いOSなど)で開始した場合に、開始が止まり理由が通知されることを確認する。

## Pythonサーバーの単体試験

リポジトリルートでPython 3.14の専用コンテナからサーバーの単体・契約試験を実行します。

```bash
docker compose -f server/compose.test.yml run --build --rm test
```

## TLS・接続境界のコンテナ結合試験

`integration`サービスは`integration` profileで単体試験と分けて実行します。テストプロセス内で実サーバーをTLS必須・認証ありで起動し、固定版の`httpx`と`websockets`からloopbackの実TCP接続を行います。外向き通信やホスト側ポート公開はありません。

```bash
docker compose --profile integration -f server/compose.test.yml run --build --rm integration
```

接続するたびにOpenSSLで一時CA・証明書・秘密鍵を生成し、テスト内で資格情報も生成します。期限切れ・SANなし・未信頼証明書、鍵不一致、不正/期限切れ/失効token、2台目開始、停止後の再開始、無通信WSS切断、HTTP 413、WSS 1009を検証します。通信期限を0.5秒に短縮して切断検知と所有権解放を測り、watchdogと登録処理taskの残留も確認します。HTTP応答は`contracts/schemas/`と`contracts/fixtures/errors.json`、WSS上限は`contracts/fixtures/binary-message-boundaries.json`に照合します。別資格情報のTLS実接続については、所有者以外のDELETEが403 `FORBIDDEN`、2台目POSTが409 `SESSION_IN_USE`となることをHTTP error fixture/schemaに照合し、別資格情報WSSから既存sessionのsession_id/generationを持つ有効frameを送った場合にclose 1008で拒否されることを確認します。各拒否の後もsession状態・owner_id・generationが不変で、所有者本人が停止できることを検証します。

WSSクライアントは、`server/tests/integration/ws_client.py`の`SyncWebSocket`（`websockets.asyncio`を専用イベントループで動かす同期API）を使います。websocketsの同期クライアントは、1つのTLS接続を受信threadとメインthreadが同時に読み書きし、稀にHTTP Upgrade要求がTCPへ送出されず60秒のhandshakeタイムアウトになったためです（Issue #174、[作業記録](../../tasks/2026-10-31_issue-174_integration-flake.md)）。`open_timeout`の延長やリトライでは対処していません。

再実行は上記コマンドをそのまま使います。実行記録には実行日、コマンド、`docker compose`/Python/OpenSSL版、`server/requirements-dev.txt`のhttpx・websockets・jsonschema版、テスト件数、成功/失敗を残します。実行時のOpenSSL版は`docker compose --profile integration -f server/compose.test.yml run --rm integration openssl version`で確認できます。

`GET /api/v1/ready`はモデル準備状態の確認であり、session状態取得には使いません。session状態はWSS text state通知（`accepted` / `processing` / `ready` / `stopped`）で受け取り、各通知のsession_id・generation・dictionary_revisionを`contracts/schemas/stream-message.schema.json`で検証します。独立したsession状態取得・再選択APIはありません。再選択時はClientが送信停止・旧generation無効化・表示消去を先に行い、DELETEで旧sessionを解放後、新ROIで利用者が明示的にPOSTして新sessionを作ります。結合試験では現session IDの上下generation不一致frame拒否、現generation frameのsession検証通過、停止後のWSS close、所有権・taskの解放を確認します。Windows実機との通信、画面取得・表示、およびWindows/Linux間E2Eはこのコンテナ試験の対象外で、#108等で実施します。

## 実エンジンと画像処理・結果配信の結合試験 (Issue #80)

実Tesseract・実Argos Translate・実TLS/WSSの本物のappをコンテナ内で組み合わせ、固定画像から訳文までを検証します。ファイルは`server/tests/integration/test_pipeline.py`(画像→訳文の契約・品質、位置不明、多フレーム)と`test_pipeline_resilience.py`(準備失敗→復旧、負荷中の停止/再選択/切断、遅い購読者、後始末)です。共通部品は`pipeline_case.py`・`pipeline_support.py`・`live_server.py`です。

### 事前準備 (モデル)

`integration`サービスは外向き通信を持たない(`network_mode: none`)ため、Argos英日モデルは事前に別サービスで名前付きボリューム`argos-models`へ導入します。

```bash
docker compose -f server/compose.test.yml --profile model run --build --rm prepare-model
docker compose -f server/compose.test.yml --profile integration run --build --rm integration \
	python -B -m unittest discover -s tests/integration -p "test_pipeline*.py" -v
```

`prepare-model`は`server/tests/fixtures/pipeline/model-manifest.json`の固定manifest(版1.1、120,470,284 bytes、SHA-256 `16300cc4...f716`)で取得・検証し、Argosへ導入して1度翻訳することでStanza資源も保存します。所要時間は、初回が約20秒(約115 MiBの取得を含む。開発機1台での実測で、回線条件は統制していない)、取得済みの再実行が約5秒です。ボリュームが残る限りキャッシュされ、ボリュームを削除しない限り再取得しません。モデル未準備のまま試験を実行した場合は**skipせず失敗**し、上記の準備コマンドを表示します。なおこのmanifestのライセンス欄は、利用・再配布条件を未確認のまま試験用に取得するという記録です(同梱・再配布しない)。製品の信頼済みdigestとライセンス確認は#81/#109側の課題です。

CIの`server`ジョブは単体試験のみで、この実エンジン結合試験は含みません(約115 MiBの外部取得が必要なため)。ローカルと独立レビューで上記コマンドを実行し、結果を作業記録とPR本文に残します。

### 固定画像

`server/tests/fixtures/pipeline/`の画像はすべて`generate.py`が自前で描画しており、第三者の画像権利を含みません(文字はコンテナ同梱のDejaVu Sans)。`cases.json`が正解文・分類・SHA-256を持ち、試験が画像との一致を検査します。再生成は`generate.py`の先頭に記載のコマンドで行います。

| 群 | 枚数 | 内容 | 期待 |
| --- | ---: | --- | --- |
| clear | 6 | 白地黒文字の英文(複数行1枚) | 総CER 5%以下、`status: ok`、訳文が日本語 |
| complex | 4 | グラデーション・縞・ノイズ・市松の背景 | 契約に合い、信頼度0.45以上の領域だけを返す。CERは**測定のみ** |
| empty | 2 | 白一色・黒一色 | `status: empty`、領域なし |
| unreadable | 1 | 乱数ノイズ | `status: empty`、領域なし |

OCRの評価は[受入計画](acceptance.md)と同じ正規化・総編集距離/正解文字数でCERを計算します。

### 検証内容

- 画像→訳文: 11枚を1sessionでWSS送信し、各結果が`stream-message.schema.json`に合い、`processing`→`ready`→`result`の順と同一`correlation_id`、session・generation・dictionary_revision・画像寸法の一致、領域が画像内であることを確認します。
- 位置不明: 実OCRの文字はそのまま、位置だけを不明/画像外にして返す薄い包み(`UnpositionedOcr`)で、`rect: null`のまま訳文が配信されることを確認します。実Tesseractは常に位置を返すため、位置不明そのものの実エンジン再現はできていません。
- 多フレーム: 実OCRを`Event`で保留して後続3枚を待機枠へ入れ、置換された枚が実OCRに渡らず1枚目と最新(4枚目)だけが結果になることを確認します。同期は`Event`と破棄通知の`Condition`だけで、固定sleepは使いません。
- 準備失敗→復旧: 未導入→`MODEL_NOT_READY`(503)、破損モデル→失敗理由に内容を含めず503のまま、正しいモデル配置後に実エンジンのロードとwarmupでreadyとなり、実画像の翻訳が通ることを確認します。
- 製品起動経路のready反映(#194): `create_app(readiness=LifecycleReadiness(...))`で、準備中は`/api/v1/ready`・セッション開始が理由付き`MODEL_NOT_READY`(503)、`/api/v1/health`は200、準備完了で自動的に200/201、未導入・破損では理由(パス・内容を含まない)付き503のまま再試行で復旧、停止時は準備ループを取り消してreadyを落とすことを`server/tests/test_lifecycle_readiness.py`で確認します。待機は`threading.Event`・注入sleep・Queueで同期し、固定sleepを条件にしません。実エンジンでは`server/tests/integration/test_startup_ready.py`が、試験側のready補完なしに`LifecycleReadiness`だけで200になり翻訳できることを確認します。
- 負荷中の停止・再選択・切断: 実OCR保留中に停止/切断/再選択し、旧sessionの結果が配信されず、再選択後の新sessionに旧結果が混ざらないことを確認します。
- 遅い購読者: 読み出さない購読者を足しても購読キューが上限(8)で止まり、古いイベントの破棄が数えられ、正常な接続は全結果を受け取ります。
- 後始末: 各試験の終了時に、購読0、worker 0、待機画像0、保持結果0、stream 0、sessionなしを確認します。
- エンジン/モデル版: Tesseract、pytesseract、argostranslate、ctranslate2、stanza、pillow、モデルmanifest版、導入済みモデル版を試験出力(`engine_versions=`)と作業記録に残します。

### 品質基準に対する結果と未達・未検証

| 項目 | 結果 |
| --- | --- |
| 明瞭群CER 5%以下 | 6枚で0.0%。**ただし6枚の小標本**であり、ACC-13の200枚(各100枚)の判定ではない |
| 複雑背景群CER 15%以下 | #182の改善で、4枚の自作画像は**56.2%から0.0%**(基準内)。**ただし自作4枚の小標本で、手法を当てはめた画像でもある**ため、改善の証明ではない。同じ前処理を未調整の追加画像(自作・非固定、下記)へ当てると背景が左右で明暗に分かれる画像と高コントラストの市松模様では誤り率が53〜100%で、**基準を満たす保証はない**。最終判定はACC-13の正解付き200枚(#109) |
| 翻訳品質(主旨・重大逆転・用語100%) | 画像経由の明瞭群で日本語訳が出ることのみ確認。固定100文の判定は未実施 |
| 性能(p50/p95)・8時間・CPU/メモリ | 未実施(#109)。本試験はコンテナの2 CPU/4 GiB上限下で動作する確認のみ |
| Windows描画を含むE2E | 未実施(#108等) |

「読めない文字を成功扱いにしない」(REQ-NF-003)については、空・ノイズ画像を`empty`で返すこと、信頼度0.45未満の単語を捨てることに加え、#182で**領域の平均信頼度0.60未満を訳文にしない**下限を追加しました。

### 複雑背景OCRの改善 (#182)

OCRは`server/src/screen_translation_server/engines/robust_ocr.py`(server専用。Web版の共有`src/app/ocr.py`は変更しない)で、前処理を`ocr_preprocess.py`、候補選択・信頼度選別を`ocr_select.py`の純粋関数に分けています。依存は追加していません(Pillowのみ)。

方式: ①3倍拡大→メディアンフィルタ(5)→大津の二値化→黒文字・白背景へ正規化→白縁追加でOCR。②平均信頼度が0.80未満なら、2倍拡大+コントラスト正規化のグレースケールでも認識し、信頼度の高い方を採用。③領域平均信頼度0.60未満は捨てる。拡大後が600万画素を超えないよう倍率を下げる(縮小はしない)。

固定画像13枚(実Tesseract 5.5.0、信頼度下限0.45)での測定:

| 方式 | 明瞭群CER(6枚) | 複雑背景群CER(4枚) | 備考 |
| --- | --- | --- | --- |
| 改善前(グレースケール+自動コントラスト+コントラスト1.8倍+2倍拡大) | 0.0% | 56.2% | 2枚無出力、1枚は信頼度0.32の誤認識(下限で除外) |
| 2倍拡大+コントラスト正規化のみ(コントラスト強調なし) | 0.0% | 9.2% | グラデーション背景で文字周辺の模様を誤読 |
| 2倍拡大+二値化(メディアン5) | 0.0% | 21.5% | 細い文字が欠け、グラデーション画像が無出力 |
| 2倍拡大+二値化(メディアンなし) | 0.0% | 11.5% | |
| **採用: 3倍拡大+メディアン5+大津二値化(+グレースケール候補)** | **0.0%** | **0.0%** | 全体平均信頼度0.95、領域下限0.60でも出力は変わらない |

処理時間(同一コンテナ・2 CPU・各画像3回、中央値/最大): 改善前は明瞭124/387 ms、複雑149/961 ms、改善後は明瞭134/167 ms、複雑169/279 ms。フル画面画像・p50/p95は未測定(#109)。

試した手法と結果: 倍率(2/3倍)・メディアンの有無と大きさ(0/3/5)・コントラスト強調の有無・局所平均との差による適応しきい値(自作の追加画像で効果が限定的かつ複雑さに見合わず不採用)。

補足の探索(自作・非固定・ゲート外。再現スクリプトは未コミット): 28px/20pxの3文で、背景が左右で明暗分割(白縁取り文字)は誤り率約70%(改善前76%)、高コントラスト市松+縁取りは90〜100%(改善前100%)、色付きノイズ背景と低コントラスト背景は0%(改善前は35%・0%)。大津の二値化は画像全体で単一のしきい値を使うため、明暗が混在する背景に弱いことが原因です。

**誤表示と無表示のトレードオフ**: 領域平均0.60未満を捨てるため、読めない難例では「訳文が出ない」方向に倒れます(例: 市松背景は無出力)。誤認識を訳文として出すより、利用者が読めない状態を選んだ判断です。0.60は固定画像で正しい結果が全て0.9以上、疑わしい誤認識が0.5前後だった観測に基づく仮置きで、適切な値は#109の200枚で再評価が必要です。下限を下げれば無表示は減りますが誤表示が増えます。

**Ownerへ提示すべき事項**
- 対象要件: REQ-NF-003(複雑背景群CER 15%以下、ACC-13)。自作4枚では基準内だが、200枚での達成は未検証。
- 未達が見込まれる原因: 背景が明暗で混在する画像(ゲーム画面で多い)・高コントラストの縞/市松と縁取り文字。大津の単一しきい値と、Tesseractが自然画像向けでないことによる。
- 代替案: ①局所しきい値と文字色クラスタリングによる文字領域の分離、②Web版が持つ`tesseract_llm_fallback`相当(LLM OCR)をserverのオプションに追加(外部送信禁止の要件REQ-F-004との整合が必要)、③複雑背景群の基準・対象の再定義(例: 縁取り文字・高コントラスト背景を対象外にする)、④信頼度下限0.60の緩和(誤表示を許容)。いずれも#109の結果を見て判断する。

### 未解決事項 (製品側)

- Argos Translateの文分割(Stanza)は、既定では翻訳初回に外部(GitHub等)から資源一覧を取得し、外向き通信がないと最初の翻訳が失敗します。本試験は、取得済み資源だけを使う設定(`download_method=reuse_resources`)を試験側でStanzaへ与えて外向き通信なしで実行しています。製品サーバーを外向き通信なしで運用する場合は、同じ設定を製品側へ入れるか、準備段階で資源を取得する必要があります(#81/#109/#173の検討事項)。翻訳対象の文章を外部へ送るものではありません。
- (解消済み・#173) 停止(DELETE)で待機中frameへ`pipeline.cancel`が呼ばれず、停止済みsessionの待機frameにも実OCRが走っていた件は、DELETEで`cancel`を別taskとして呼び、待機frameの取り出し時にもsession・世代・revisionを再照合してOCR前に破棄することで解消しました(`server/tests/test_delivery_diagnostics.py`)。

## サーバー全体の設定更新・再起動結合試験 (Issue #85)

R2(#76〜#84)の各Phaseをまたぎ、認証・準備確認・セッション・実エンジン翻訳・辞書/設定の更新と永続化・停止・再起動・再翻訳を、実TLS/WSSの本物のappで通します。ファイルは`server/tests/integration/test_server_scenario.py`(試験)と`scenario_support.py`(再起動・ログ捕捉・同期の部品)です。事前準備は#80と同じ(`prepare-model`済みのボリュームが必要。未準備なら**skipせず失敗**)。

```bash
docker compose -f server/compose.test.yml --profile integration run --build --rm integration \
	python -B -m unittest discover -s tests/integration -p test_server_scenario.py -v
```

**本番と同じ経路**: 保存先は環境変数`SCREEN_TRANSLATION_DATA_DIR`、pipelineはappが最初のframeで`create_default_pipeline`により作る経路(辞書wrapper・保存済みfpsを引き継ぐ)です。重い実エンジンだけを共有し、pipeline生成関数を差し替えています。

**「再起動」の定義**: 同じ保存先・資格情報・証明書のまま、listener・Session・辞書とキャッシュ・pipelineを止めて新しく作り直します(プロセス再起動の再現)。コンテナの停止・起動、名前付きvolumeの再マウントはこの試験では行っていません(下の未検証)。

### 検証内容

| 試験 | 内容 |
| --- | --- |
| 全体シナリオ | 未認証401→準備前503(readyとsession開始)→準備後200→セッション開始→翻訳→辞書(管理token+If-Match)と設定の更新(`ETag`・`X-Effective-From: next-frame`、pipelineのfps反映)→更新前revisionのframeは切断せず破棄→更新後revisionのframeに辞書訳(キャッシュ失効の確認)→停止→再起動→辞書・設定・revisionが一致→旧session_idは404、旧session_id付きframeは1008で拒否、再度POSTが必要で新しいsessionはgeneration 1・保存済みrevisionから開始→再翻訳で辞書が効き、新pipelineが保存済みfpsを使う |
| 同時更新 | 同じ`If-Match`の2要求をBarrierで同時に解放し、200と409が1件ずつ、409の`ETag`が最新revision、保存値・実行中revisionが勝者と一致、敗者が読み直して再試行できる、再起動後も一致 |
| 保存失敗 | 保存関数が失敗(例外文字列に目印を含める)したとき500 `INTERNAL_ERROR`、保存済み・実行中の辞書とrevisionが不変でframeも破棄されず、障害解消後に同じrevisionで更新できる |
| モデル準備失敗 | モデル未導入のlifecycleがunreadyを返す間はsession開始が503 `MODEL_NOT_READY`でも辞書更新は成功し、再起動後に実エンジンで反映される |
| 処理中の更新 | 実OCRを`Event`で保留中に辞書を更新し、旧revisionのframe結果は配信前に破棄され、次のframeだけが新辞書で配信される |
| 切断中の更新 | 処理中に切断し、その間に辞書を更新。次のsessionは新revisionから始まり、旧sessionの結果・状態が届かない(購読・worker・待機画像の残留なし) |
| ログ | 運用の既定(INFO)で出る全ログと自サーバーのDEBUGに、端末/管理token・原文・訳文・辞書訳・保存失敗の例外文字列とパスが出ない。session_idは診断ログに出ない(下の例外を除く) |
| 待ち時間の上限 | `read_until`に全体の期限を設け(`overall_timeout`、既定180秒)、条件に合わないmessageが続いても失敗が早く分かる。注入クロックの単体試験つき。`drain_until_closed`にも同じ期限 |

同期は`Event`・`Barrier`・破棄通知の`Condition`・サーバーloop内の状態待ちだけで、固定sleepを同期条件にしていません。timeoutは無応答時の失敗検出専用で、watchdogは合否条件にしていません。

### 未解決事項・未検証 (#85)

- **未検証**: コンテナの停止・起動をまたぐ名前付きvolumeの永続、製品の起動経路(`main`)での再起動。8時間連続稼働、性能(p50/p95)、Windows実機を含むE2E、複数端末の同時利用は#108/#109。
- **製品の起動経路**: `main()`は`create_app()`を`is_ready=False`で起動し、`EngineLifecycle`のreadyをappへ反映する配線が見当たりません。本試験はlifecycleのreadyを試験側で反映しており、製品起動でsessionが開始できるかは未検証です(要確認の課題)。
- **uvicornのaccessログ**: `DELETE /api/v1/sessions/{session_id}`のパスにsession_idが出ます。診断ログへsession_idを出さない不変条件([security.md](design/security.md))の対象外ですが、運用ログには残ります。accessログの抑止またはパス伏せが必要です(本試験は`uvicorn.access`をsession_id検査から除外し、token・訳文は含めて検査)。
- **第三者ライブラリのログ**: `argostranslate`はINFOで原文・訳文をログに出し、rootにhandlerを足すと漏れます(既定では出力先がありません)。本試験は`argostranslate`のloggerを検査から除外しています。製品側で当該loggerを抑止する対処が必要です。運用でroot loggerにhandlerを付ける場合は注意してください。
- **Stanza資源の外部取得**: #80と同じく`download_method=reuse_resources`を試験側で与えています(#189)。

## 変更後の回帰・静的検査

サーバーや共通処理を変更した場合は、通常のサーバー試験に加え、アプリ用イメージとリポジトリをマウントした回帰試験を実行します。

```bash
docker build -t app:ci . && docker run --rm -e PYTHONPATH=/app/src app:ci python -B -m unittest discover -s src/tests
docker compose -f server/compose.test.yml run --build --rm -v "$PWD:/workspace:ro" -e PYTHONPATH=/workspace/src:/workspace/server/src test python -B -m unittest discover -s server/tests
docker run --rm --cpus=2 -e PYTHONPATH=/workspace/src:/workspace/server/src -e MYPYPATH=/workspace/src:/workspace/server/src -v "$PWD:/workspace:ro" -w /workspace app:ci mypy --cache-dir=/tmp/mypy_cache server/src
docker run --rm --cpus=2 -e PYTHONPATH=/workspace/src:/workspace/server/src -e MYPYPATH=/workspace/src:/workspace/server/src -v "$PWD:/workspace:ro" -w /workspace app:ci mypy --cache-dir=/tmp/mypy_cache src
docker run --rm --cpus=2 -e PYTHONPATH=/workspace/src:/workspace/server/src -e MYPYPATH=/workspace/src:/workspace/server/src -v "$PWD:/workspace:ro" -w /workspace app:ci mypy --cache-dir=/tmp/mypy_cache --platform win32 src
docker run --rm --cpus=2 -e PYTHONPATH=/workspace/src:/workspace/server/src -v "$PWD:/workspace:ro" -w /workspace app:ci ruff check --no-cache server/src server/tests
```

コンテナ外の実機情報・秘密値・生成した鍵は記録やリポジトリへ保存しません。失敗した場合は失敗したコマンドと要約を先に記録し、修正後に同じコマンドを再実行します。

## 2026-10-31 PR #168 レビュー指摘の再検証

| 試験 | 結果 |
| --- | --- |
| server Compose unit | Python 3.14.7、125件成功、3件skip |
| server integration profile | 13件成功（#174で同期クライアント包みの4件を追加） |
| client Compose tests | Client 68件、Contracts 4件成功 |
| app:ci 全体試験 | 309件成功、75件skip |
| read-only mount server回帰 | 118件成功、3件skip |
| mypy `server/src` | 22 source files、問題なし |
| mypy `src` / Windows platform | 各79 source files、問題なし |
| ruff `server/src server/tests` | 成功 |
| 結果配信ログ秘匿test | 13件成功。2診断ログへ`session_id`を戻すmutationは失敗し、復元後は成功 |

read-only mount回帰でschemaの探索先が配置依存になっていたため、`test_result_delivery.py`は親ディレクトリからschemaを探索します。通常のCompose配置とread-only mount配置の両方で回帰を確認しています。

## 2026-10-31 実行記録

| 試験 | 実行環境・版 | 結果 |
| --- | --- | --- |
| server単体・契約 | Python 3.14.7 | 101件成功、3件skip |
| TLS/接続境界integration | Python 3.14.7、OpenSSL 3.5.7、httpx 0.28.1、websockets 15.0.1、jsonschema 4.26.0 | 13件成功（Issue #165の所有権ケースと、#174の`SyncWebSocket`試験4件を含む） |
| app:ci全体試験 | Python 3.14 | 308件成功、74件skip |
| read-only mount server回帰 | Python 3.14.7 | 94件成功、3件skip |
| mypy `server/src` | app:ci / mypy 1.18.2 | 19 source files、問題なし |
| mypy `src` / Windows platform | app:ci / mypy 1.18.2 | 各79 source files、問題なし |
| ruff `server/src server/tests` (`--no-cache`) | app:ci / ruff 0.16.1 | 成功 |

実行コマンド・Issueへの記録は [Issue #74作業記録](../../tasks/2026-10-31_issue-74_session-integration.md)、[Issue #165作業記録](../../tasks/2026-10-31_issue-165_session-ownership-tests.md)、Issue #74の試験結果Commentを参照してください。
