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

```bash
docker compose -f client/compose.test.yml run --build --rm test
```

```powershell
dotnet test client/tests/ScreenTranslation.Windows.Tests/ScreenTranslation.Windows.Tests.csproj --configuration Release --filter Category=CaptureIntegration
```

CaptureIntegrationはWindows専用で、Linuxでは対象プロジェクトがビルドされません。Linuxでのskipをこの試験の合格として扱いません。この試験はWin32 `PrintWindow`で取得した画素を使い、**Windows Graphics Capture(WGC)の画素読み出しは検証しません**。現状の本番コードはWGCの`FrameArrived`で画素を読み出して`CapturedFrame`へ変換する処理を持たない(対象の有効性確認のみ)ため、WGC取得から送信までの結合は未実装・未検証です。追跡は #135/#148系の実機Taskに委ねます。

### Owner実機手順 (混在DPI・複数モニター・画面表示)

hosted runnerで再現できない項目です。担当: Owner。**結果: 未実施(Windows実機が必要)**。実施した場合は日付、Windows版、モニター構成(解像度・DPI・配置)、合否をIssueへ記録し、この欄を更新してください。

1. 倍率が異なる2台以上のモニター(例: 100%と150%)、および主モニターより左/上に置いた(負座標の)モニターを用意する。
2. 各モニターの既知の目盛り/文字を持つウィンドウでROIを選択し、取得開始する。受信側(またはサーバーログの画像寸法)でROI寸法が選択した物理pxと一致し、目盛り位置のずれが2 physical px以下であることを確認する。
3. 取得中に対象ウィンドウを閉じる/最小化する/別モニターへ移動してDPIを変える/取得権限を拒否する。送信が止まり、旧領域の画像がそれ以降送られず、取得sessionが解放される(再開始まで送信されない)ことを確認する。
4. 負荷(別プロセスでCPUを飽和)をかけた状態でROIを再選択し、再選択前の領域の画像が受信されないことを確認する。
5. 取得除外(自己キャプチャ除外/WDA)が失敗した場合に送信が停止することを確認する(#135/#136系)。

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
- 負荷中の停止・再選択・切断: 実OCR保留中に停止/切断/再選択し、旧sessionの結果が配信されず、再選択後の新sessionに旧結果が混ざらないことを確認します。
- 遅い購読者: 読み出さない購読者を足しても購読キューが上限(8)で止まり、古いイベントの破棄が数えられ、正常な接続は全結果を受け取ります。
- 後始末: 各試験の終了時に、購読0、worker 0、待機画像0、保持結果0、stream 0、sessionなしを確認します。
- エンジン/モデル版: Tesseract、pytesseract、argostranslate、ctranslate2、stanza、pillow、モデルmanifest版、導入済みモデル版を試験出力(`engine_versions=`)と作業記録に残します。

### 品質基準に対する結果と未達・未検証

| 項目 | 結果 |
| --- | --- |
| 明瞭群CER 5%以下 | 6枚で0.0%。**ただし6枚の小標本**であり、ACC-13の200枚(各100枚)の判定ではない |
| 複雑背景群CER 15%以下 | 4枚の自作画像で**56.2%(未達)**。2枚は無出力(信頼度不足)、1枚は誤認識を信頼度0.51で返し、1枚は誤りを含んで返した。正解付きの実標本200枚での判定とOCR前処理の改善は#109等で行う |
| 翻訳品質(主旨・重大逆転・用語100%) | 画像経由の明瞭群で日本語訳が出ることのみ確認。固定100文の判定は未実施 |
| 性能(p50/p95)・8時間・CPU/メモリ | 未実施(#109)。本試験はコンテナの2 CPU/4 GiB上限下で動作する確認のみ |
| Windows描画を含むE2E | 未実施(#108等) |

「読めない文字を成功扱いにしない」(REQ-NF-003)については、空・ノイズ画像を`empty`で返すこと、信頼度0.45未満の領域を返さないことは確認できました。一方、複雑背景で誤認識を中程度の信頼度のまま訳文にして返す事例があり、信頼度の下限だけでは防げていません。

### 未解決事項 (製品側)

- Argos Translateの文分割(Stanza)は、既定では翻訳初回に外部(GitHub等)から資源一覧を取得し、外向き通信がないと最初の翻訳が失敗します。本試験は、取得済み資源だけを使う設定(`download_method=reuse_resources`)を試験側でStanzaへ与えて外向き通信なしで実行しています。製品サーバーを外向き通信なしで運用する場合は、同じ設定を製品側へ入れるか、準備段階で資源を取得する必要があります(#81/#109/#173の検討事項)。翻訳対象の文章を外部へ送るものではありません。
- 停止(DELETE)では待機中のframeに対する`pipeline.cancel`が呼ばれず、停止済みsessionの待機frameにも実OCRが走った後で破棄されます(停止試験で実OCR 2回を観測)。結果は配信されず後始末も完了しますが、無駄なOCRが1回走ります(#173のapp配線で扱う候補。本Taskでは未変更)。

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
