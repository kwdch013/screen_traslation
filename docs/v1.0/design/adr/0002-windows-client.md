# ADR-0002 Windows UI・画面取得・配布の候補

## 状態

2026-10-30、**設計採用**。Windows 11 25H2 x64のWPF/.NET 10、WGC、WDA_EXCLUDEFROMCAPTURE、Per-Monitor V2、win-x64自己完結配布を採用する。API相互運用・自己取得除外・混在DPI・配布のWindows実機検証は未実施。#135/#136相当の実機Taskで確認する。[索引・検証課題](README.md) / [基本・詳細設計](../architecture.md)。公式資料調査は[画面取得・キャプチャ除外調査](../../research/capture-exclusion.md)と[混在DPI調査](../../research/mixed-dpi.md)を参照。

## 対象要件

REQ-F-001、REQ-F-002、REQ-F-005、REQ-F-006、REQ-F-012、REQ-NF-008、REQ-NF-009、REQ-NF-010。

## 背景

Owner承認済みのWindows 11 25H2 Home/Pro x64と.NET 10 LTS安定SDKを前提に、領域選択・非アクティブ重畳・混在DPIを満たすUI/取得APIを選ぶ。専用GPUを必須にせず、保護対象の回避をしない。SDKのパッチは #57/#68 のglobal.jsonで固定し、ここで最新パッチを推測しない。

## 比較

| 候補 | 利点 | 制約・今回の判断 |
| --- | --- | --- |
| WPF + Win32連携 | .NET標準のUI、XAMLとHWNDを利用して表示/制御を分離できる | DPI変換、非アクティブ/クリック透過、WGC相互運用の実証が必要。推奨候補 |
| WinUI 3 + Windows App SDK | Windows向けのUIとWGC連携候補 | 追加ランタイム/配布と重畳の検証が増える。WPF不成立時の比較先 |
| WinForms + Win32連携 | HWND制御を直接扱いやすい | 多行表示/レイアウト/DPIの作り込みが必要。代替候補 |
| WGC + WDA_EXCLUDEFROMCAPTURE | 利用者が選ぶ画面/ウィンドウ取得と自己ウィンドウ除外 | 除外APIの成功だけでは全対象の動作保証にならない。推奨取得候補 |
| Desktop Duplication / GDI系 | 画面単位の取得の比較材料 | 対象選択/自己混入/資源条件を別途評価。無断フォールバックしない |

## 採用方式

WPFで操作画面と独立した非アクティブ/クリック透過の重畳を作り、Windows.Graphics.Capture（WGC）で利用者が明示選択した対象を取得する。WDA_EXCLUDEFROMCAPTUREを自身のトップレベル重畳HWNDへ設定する。これはDRMや保護画面取得の保証ではない。対象消失・最小化・保護・除外失敗を判別できない場合はfail-closedで取得/送信を止め、再選択を案内する。除外失敗を重畳非表示の瞬間取得だけで解決済みにしない。

Per-Monitor V2を採用し、選択UIのDIPと取得画像/契約の物理画素を分ける。DPIや対象サイズ変更時は古い変換を破棄して世代を更新する。座標原点・丸め・モニター境界の契約は #63 で確定し、実機誤差は #136 で測定する。純粋な算術モデル/公式資料だけではOS API・WPF/WGC統合結果を保証しない。

配布はwin-x64自己完結とし、利用者へSDKを要求しない。単一ファイル化/トリミング/Native AOTは必須にせず、WPFと取得ライブラリの実動作を優先する。手動更新と設定退避/復旧を提供し、自動更新は対象外。

## 検証と確定担当

Q-02の公式資料/再現手順は #58で整備済み、Q-03の公式資料/純粋算術モデル/実機手順は #59で整備済み。**Windows実測は未実施**で、#135が取得API/自己取得除外、#136が混在DPI/負座標/重畳を検証する。2画面以上・100%/150%/200%・負座標・対象移動/リサイズ、通常/全画面/保護対象、フォーカスとクリック先を試す。ROI各隅誤差2 physical px以下、自己混入なし、失敗時停止をACC-03/ACC-06/ACC-07で個別判定する。Linuxテストや単一DPIのrunnerだけでは合格にしない。

Q-10は #57/#68 で方式を設計し #104/#108 でSDKのないWindowsへ導入する。署名検証には購入を伴わない専用の試験用自己署名コード署名証明書とSignToolを候補とし、隔離した試験用信頼領域で正しい配布物/改ざん配布物を比較する。TLS用証明書と鍵は流用しない。信頼元の公開情報/digestは別の確認済み経路で配り、未確認の証明書を無条件に登録しない。

## 影響

自己署名で検証できるのは試験内の署名・改ざん検知であり、一般端末での公開発行元の信頼や警告解消を証明しない。OS保護を無効化する導入手順は採用しない。実配布の署名方針は #57/#104 で確定し、有料証明書が必要なら購入前にOwnerへ確認する。要求不達ならAPI/UI代替と影響IDを提示し、無断で対象OSや誤差を緩めない。

## 根拠

2026-10-29確認: [WPF概要](https://learn.microsoft.com/en-us/dotnet/desktop/wpf/overview/)はWindows向け.NET UI、[画面取得](https://learn.microsoft.com/en-us/windows/apps/develop/media-authoring-processing/screen-capture)はWGCと利用者選択を説明する。[除外API](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowdisplayaffinity)は対象HWNDと保護の限界を明記する。[DPI指針](https://learn.microsoft.com/en-us/windows/win32/hidpi/high-dpi-desktop-application-development-on-windows)は動的なDPI対応が必要な根拠とする。[.NET配布](https://learn.microsoft.com/en-us/dotnet/core/deploying/)と[SignTool](https://learn.microsoft.com/en-us/windows/win32/seccrypto/signtool)を配布検証の参考とする。[.NETサポート方針](https://dotnet.microsoft.com/en-us/platform/support/policy/dotnet-core)は実装時に再確認し、サポート中安定SDKを固定する。これらは候補APIの根拠であり、本アプリでの実証は別途必要。

## 対象ウィンドウの移動・リサイズ(Issue #198)

取得中のウィンドウ対象で、ROIは選択時の`Bounds`左上を原点としたローカル座標に変換して取得する。ウィンドウが動くと、物理座標のROIと重畳位置が実際の位置とずれる。契約([座標](../../../../contracts/coordinates.md)・[状態](../../../../contracts/session-state.md))とACC-06(移動後も四隅の誤差2 px以下、古い座標を継続しない)に沿って次を採用する。

- **同じ大きさの移動は追従する**: ローカルROIは変えず、物理ROIを新しい左上へ合わせ直す。ウィンドウ上の同じ領域を送り続けるため、利用者の再操作は不要。位置が変わるたびに世代を進め、旧位置の待機画像・通信中の送信・表示を破棄し、旧位置のフレームと結果は世代照合で拒否する(旧座標の画像を送らない・誤った位置へ重畳しない)。
- **大きさが変わる場合は追従しない**: リサイズで「ウィンドウのどの部分か」というROIの意味が変わり、左・上端のリサイズでは内容の原点も動く。意味を推測して送るより止める方が安全なため、送信と表示を同期的に止め、対象とROIを破棄して選び直しを求める(fail-closed)。取得側(WGC)が新しい大きさのフレームを返した場合も、そのフレームは読み出さず同じ停止にする。
- DPIが異なるモニターへの移動は、ROIの物理画素数が変わるため従来どおり停止する。

却下した案: 常に停止して再選択を求める(同じ大きさの移動で毎回操作が必要になり、ACC-06の「移動後も四隅の誤差2 px以下」を満たす余地を捨てる)、リサイズでも比率でROIを変換して追従する(認識対象の内容が変わるため誤送信になりうる)。実機での四隅誤差は[#136](../../testing.md)で測定するまで未実施。

