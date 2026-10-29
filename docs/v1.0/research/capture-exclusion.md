# Windows 画面取得とオーバーレイ自己キャプチャ除外の調査

## 状態と結論

- 調査対象: Windows 画面取得 API と `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)` による自プロセスのオーバーレイ除外。
- 公式資料から分かること: API の導入 OS、呼び出し条件、文書化されたエラーや制限を以下に整理した。
- 実機結果: **未実施(Windows実機が必要)**。Linux では Windows の DWM・WGC・DXGI・GDI の合成結果を検証できない。
- 対応要件・受入: REQ-F-001 / ACC-03 (対象取得)、REQ-F-005 / ACC-07 (重畳・自己取得防止)、REQ-NF-008 / ACC-06 (Windows環境)。
- 採否: 未確定。公式資料だけでは、対象要件の Windows 11 25H2 上で各取得経路が WDA 設定済みのオーバーレイを除外するか確定できない。実機検証の結果を ADR-0002 と Q-02 へ反映する。
- 特定の実機、ユーザー、接続先情報は記録しない。

## 公式資料で確認できた事実

| 方式・機能 | 対応 OS / 呼び出し条件 | 文書化された挙動・制約 |
| --- | --- | --- |
| `Windows.Graphics.Capture` (WGC) | `GraphicsCaptureItem` は Windows 10 version 1803 (build 17134) で導入。Win32 の HWND を item にする `IGraphicsCaptureItemInterop::CreateForWindow` は Windows 10 version 1903 (build 18362) 以降。 | `GraphicsCaptureSession.IsSupported()` で利用可否を確認する。Picker は利用者に対象を選ばせ、システム UI に取得中の黄色い枠を表示する。Microsoft はデバイスのハードウェア要件などで非対応の場合があるとしている。公式資料は WDA と組み合わせた自己除外結果を保証していない。 |
| DXGI Desktop Duplication | Windows 8 で導入。モニター単位でデスクトップ画像を取得する。 | `AcquireNextFrame` が `DXGI_ERROR_ACCESS_LOST` を返す例はデスクトップ切替、表示モード変更、DWM の on/off 切替や全画面アプリへの切替。古い duplication interface を破棄して再作成する。前フレームを `ReleaseFrame` する前に再度取得すると `DXGI_ERROR_INVALID_CALL`。複製セッション数には上限があり、`DuplicateOutput` は既定で最大4つを超えると `DXGI_ERROR_NOT_CURRENTLY_AVAILABLE` を返す。保護コンテンツへのアクセスは保護される。 |
| GDI (`BitBlt`) | `BitBlt` は Windows 2000 以降のデスクトップ API。 | `CAPTUREBLT` を指定すると、対象ウィンドウの上にある layered window も画像に含める。指定しない場合と指定した場合の差がある。異なるデバイスの DC 間では失敗し、`BitBlt` 非対応デバイスもあり得る。WDA の除外をこの経路で保証する記載はない。 |
| `SetWindowDisplayAffinity` | 関数自体は Windows 7 以降のデスクトップアプリで利用可能。`WDA_EXCLUDEFROMCAPTURE` の意味は Windows 10 version 2004 (build 19041) 以降。それ以前では `WDA_MONITOR` と同等の扱い。 | HWND は呼び出し元プロセスに属するトップレベルウィンドウであること。失敗時は `FALSE` となり、`GetLastError` で詳細を取得する。DWM がデスクトップを合成している場合のみ機能する。公開 OS API の一部に対するウィンドウ保護機能であり、セキュリティ機能や DRM ではなく、厳密な保護を保証しない。 |

### 要件環境との関係

v1.0 の対象は Windows 11 25H2 x64 である。この OS 世代は上記の導入バージョンより新しいが、OS バージョン要件を満たす事実だけでは、WGC・DXGI・GDI のすべての組合せにおけるオーバーレイ除外や、対象アプリの取得可否を証明しない。WDA の呼び出し成功も、各取得 API から確実に消えることの証明にはならない。

このため、アプリは少なくとも WDA の戻り値と `GetLastError` を記録し、除外が使えない場合に映像取得を続けて自己混入させず、停止して利用者へ理由を示す方針とする。これは要件上の安全側の扱いであり、実装・実機動作の確認は **未実施(Windows実機が必要)**。

## 公式資料に記載されている制約と失敗モード

- WGC は `GraphicsCaptureSession.IsSupported()` が false の場合に開始しない。利用可能性は実行環境で判定する。
- HWND 取得を使う WGC 経路は `CreateForWindow` の最低要件が Windows 10 version 1903。1803 の WGC 対応を HWND interop 対応と取り違えない。
- DXGI `DXGI_ERROR_ACCESS_LOST` は desktop switch / mode change / DWM 状態や全画面状態の変化後に発生し得る。interface を再作成するまでフレーム取得を再開しない。
- DXGI `DXGI_ERROR_WAIT_TIMEOUT` は期限内に新しいフレームがなかったことを示す。これは除外成功の判定に使わない。
- DXGI `DXGI_ERROR_SESSION_DISCONNECTED` は Windows セッションの切断やユーザー切替で出力複製が停止した場合に発生する。
- DXGI `E_ACCESSDENIED` は現在の desktop image へアクセスする権限がない場合に起き得る。保護コンテンツは複製 API の保護対象であり、回避しない。
- GDI の `BitBlt` は失敗時に 0 を返す。異なるデバイス間転送などの条件を切り分け、戻り値を必ず記録する。
- WDA はトップレベルウィンドウ以外では失敗し得る。DWM 合成が無効な環境にも依存し、画面をカメラで撮影するような経路から守るものではない。
- 公式資料には、対象の WGC・DXGI・GDI 各経路と Windows 11 25H2 の組合せに対する WDA の個別保証や、v1.0 の overlay が実際に除外されるという実測値はない。

## Windows 実機検証手順

各項目は **未実施(Windows実機が必要)**。Windows 11 25H2 x64 の検証端末で、Windows SDK / .NET SDK / GPU ドライバー版を記録し、画面を記録できる検証用の無害なウィンドウだけを使う。DRM・保護コンテンツを試験対象にせず、保護を回避しない。

1. 検証アプリにトップレベルの半透明オーバーレイを表示する。オーバーレイへは毎回異なる大きなテスト文字列 (`OVERLAY-<試行番号>`) を描き、取得対象アプリ側には別の識別文字列を表示する。
2. WDA を設定しない状態で、WGC (対象 HWND)、DXGI Desktop Duplication (対象モニター)、GDI `BitBlt` (`SRCCOPY` と `SRCCOPY | CAPTUREBLT`) それぞれで基準フレームを保存する。
3. `SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)` を呼び、戻り値・失敗時の `GetLastError`・`GetWindowDisplayAffinity` の値を記録する。成功しても、各取得経路を個別に同じ条件で反復する。
4. 保存フレームを目視確認し、overlay の `OVERLAY-...` が写るかを記録する。可能なら overlay 内の固定領域を OCR / ピクセル比較し、判定手段と結果を併記する。WGC の黄色いシステム枠はアプリ overlay と区別して記録する。
5. 次の条件を各方式で繰り返し、試行ごとに **除外確認** を記録する: ウィンドウ移動・リサイズ、最小化/復元、対象ウィンドウ切替、表示モード切替、全画面アプリへの切替、DWM 状態に影響するセッション変化、ロック/ロック解除、RDP 切断/再接続、複数モニター。
6. WGC の `IsSupported`、選択キャンセル、frame-pool 再生成 / device lost、DXGI の access lost / timeout / access denied / session disconnect、GDI と WDA の失敗を意図的な負荷または通常操作で観察し、再初期化・停止・表示クリアの挙動を確認する。
7. 各条件を最低3回実行する。WDA が失敗する場合、または overlay 自己混入が一度でも確認された場合を「除外不成立」とし、取得を止めて理由を表示する動作を確認する。成功回数だけを根拠に全経路の保証へ一般化しない。

## 検証プログラム雛形 (C# / Win32 interop)

以下は WDA 設定と結果記録の最小雛形。WGC/DXGI/GDI の取得ループや UI は含まないため、各経路の取得プログラムへ組み込み、同じ試行 ID で画像とログを紐付ける。**未実行。コンパイル・実機動作とも未確認。**

```csharp
using System.ComponentModel;
using System.Runtime.InteropServices;

internal static class CaptureAffinity
{
	private const uint WdaExcludeFromCapture = 0x00000011;

	[DllImport("user32.dll", SetLastError = true)]
	[return: MarshalAs(UnmanagedType.Bool)]
	private static extern bool SetWindowDisplayAffinity(IntPtr hwnd, uint affinity);

	[DllImport("user32.dll", SetLastError = true)]
	[return: MarshalAs(UnmanagedType.Bool)]
	private static extern bool GetWindowDisplayAffinity(IntPtr hwnd, out uint affinity);

	public static (bool SetSucceeded, int? SetError, bool ReadSucceeded, uint? ReadValue) Apply(IntPtr hwnd)
	{
		if (hwnd == IntPtr.Zero)
			throw new ArgumentException("有効なトップレベル HWND が必要です", nameof(hwnd));

		var setSucceeded = SetWindowDisplayAffinity(hwnd, WdaExcludeFromCapture);
		var setError = setSucceeded ? null : Marshal.GetLastWin32Error();
		var readSucceeded = GetWindowDisplayAffinity(hwnd, out var value);
		var readError = readSucceeded ? null : Marshal.GetLastWin32Error();

		Console.WriteLine($"set_ok={setSucceeded}, set_error={FormatError(setError)}");
		Console.WriteLine($"read_ok={readSucceeded}, affinity=0x{value:X8}, read_error={FormatError(readError)}");
		return (setSucceeded, setError, readSucceeded, readSucceeded ? value : null);
	}

	private static string FormatError(int? code) => code is null
		? "なし"
		: $"{code} ({new Win32Exception(code.Value).Message})";
}
```

呼び出し例は UI の HWND が生成された後に `CaptureAffinity.Apply(hwnd)` を呼ぶ。戻り値が失敗、または読み戻した affinity が `0x00000011` 以外なら除外可能とみなさず、画像取得を続けない。読み戻し値はキャプチャ結果の代わりにならないため、手順の全 API 別フレーム検査も必要。

## 実測記録テンプレート

以下の記録は Windows 実機実施後に埋める。現時点は全項目 **未実施(Windows実機が必要)**。

```text
状態: 未実施(Windows実機が必要)
担当:
実施日 (UTC):
OS エディション / バージョン / OS ビルド:
アプリ commit / 試験プログラム commit:
.NET SDK / Windows SDK:
GPU / driver:
モニター数・解像度・拡大率:
リモートセッション有無:

試行 ID:
対象取得方式 (WGC HWND / WGC picker / DXGI / GDI):
WDA 設定値:
SetWindowDisplayAffinity 戻り値:
失敗時 GetLastError (コード / メッセージ):
GetWindowDisplayAffinity 戻り値 / 値:
IsSupported (WGC の場合):
取得 API エラー・イベント:
条件 (移動、モード変更、全画面、ロック、RDP 等):
overlay識別文字列が取得画像に写ったか:
画像判定方法 / 証跡ファイル名:
停止・通知・フレーム消去の確認:
結果 (除外成立 / 除外不成立 / 判定不能):
備考:
```

## 出典 (Microsoft 公式資料)

- [GraphicsCaptureItem class](https://learn.microsoft.com/en-us/uwp/api/windows.graphics.capture.graphicscaptureitem?view=winrt-28000) — WGC API の最低対応 OS。
- [Screen capture - Windows apps](https://learn.microsoft.com/en-us/windows/apps/develop/media-authoring-processing/screen-capture) — `IsSupported`、picker、frame pool、device lost。
- [IGraphicsCaptureItemInterop::CreateForWindow](https://learn.microsoft.com/en-us/windows/win32/api/windows.graphics.capture.interop/nf-windows-graphics-capture-interop-igraphicscaptureiteminterop-createforwindow) — Win32 HWND 取得の最低 OS。
- [SetWindowDisplayAffinity function](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowdisplayaffinity) — HWND 条件、WDA 値、Windows 10 2004、DWM 条件とセキュリティ上の限界。
- [Desktop Duplication API](https://learn.microsoft.com/en-us/windows/win32/direct3ddxgi/desktop-dup-api) — API の仕組みと frame 更新。
- [IDXGIOutputDuplication::AcquireNextFrame](https://learn.microsoft.com/en-us/windows/win32/api/dxgi1_2/nf-dxgi1_2-idxgioutputduplication-acquirenextframe) — access lost、timeout、invalid call と再生成。
- [IDXGIOutput1::DuplicateOutput](https://learn.microsoft.com/en-us/windows/win32/api/dxgi1_2/nf-dxgi1_2-idxgioutput1-duplicateoutput) — desktop access denied、同時複製数の上限、session disconnect。
- [BitBlt function](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-bitblt) — `CAPTUREBLT` と layered window の扱い、デバイス条件。
- [Capturing an Image](https://learn.microsoft.com/en-us/windows/win32/gdi/capturing-an-image) — GDI `BitBlt` による画面画像取得の例。

資料確認日: 2026-10-29。
