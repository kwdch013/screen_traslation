# ADR-0002 Windows UI・画面取得・配布の候補

## 状態

2026-10-29、提案。自己取得除外・混在DPI・配布の実証は未実施。#58/#59の結果を #57 に反映する。[索引・検証課題](README.md)。#58の公式資料調査とWindows実機検証手順は[画面取得・キャプチャ除外調査](../../research/capture-exclusion.md)を参照。

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

## 採用候補

WPFで操作画面、独立した非アクティブ/クリック透過の重畳を作り、Windows.Graphics.Capture（WGC）で利用者が明示選択した対象を取得する案を推奨する。WDA_EXCLUDEFROMCAPTUREは自身のトップレベル重畳ウィンドウへ設定する候補で、DRMや秘密保護の保証とは扱わない。対象消失・最小化・保護・除外失敗を判別し、取得/送信を止めて再選択を案内する。除外失敗を重畳非表示の瞬間取得だけで解決済みにしない。

Per-Monitor V2を候補に、選択UIの論理座標と取得画像/契約の物理画素を明確に分ける。DPIや対象サイズ変更時に古い変換を使い続けず世代を更新する。座標原点・丸め・モニター境界の最終契約は #63 で確定する。

配布はwin-x64自己完結を推奨し、利用者へSDKを要求しない。単一ファイル化/トリミング/Native AOTは必須にせず、WPFと取得ライブラリの実動作を優先する。手動更新と設定退避/復旧を提供する候補で、自動更新は対象外。

## 検証と確定担当

Q-02は #58、Q-03は #59 でWindows実機検証し #57 が採否を確定する。2画面以上・100%/150%/200%・負座標・対象移動/リサイズ、通常/全画面/保護対象、フォーカスとクリック先を試す。ROI四隅誤差2 px以下、自己混入なし、失敗時停止をACC-03/ACC-06/ACC-07で判定する。Linuxテストや単一DPIのrunnerだけでは合格にしない。

Q-10は #57/#68 で方式を設計し #104/#108 でSDKのないWindowsへ導入する。署名検証には購入を伴わない専用の試験用自己署名コード署名証明書とSignToolを候補とし、隔離した試験用信頼領域で正しい配布物/改ざん配布物を比較する。TLS用証明書と鍵は流用しない。信頼元の公開情報/digestは別の確認済み経路で配り、未確認の証明書を無条件に登録しない。

## 影響

自己署名で検証できるのは試験内の署名・改ざん検知であり、一般端末での公開発行元の信頼や警告解消を証明しない。OS保護を無効化する導入手順は採用しない。実配布の署名方針は #57/#104 で確定し、有料証明書が必要なら購入前にOwnerへ確認する。要求不達ならAPI/UI代替と影響IDを提示し、無断で対象OSや誤差を緩めない。

## 根拠

2026-10-29確認: [WPF概要](https://learn.microsoft.com/en-us/dotnet/desktop/wpf/overview/)はWindows向け.NET UI、[画面取得](https://learn.microsoft.com/en-us/windows/apps/develop/media-authoring-processing/screen-capture)はWGCと利用者選択を説明する。[除外API](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowdisplayaffinity)は対象HWNDと保護の限界を明記する。[DPI指針](https://learn.microsoft.com/en-us/windows/win32/hidpi/high-dpi-desktop-application-development-on-windows)は動的なDPI対応が必要な根拠とする。[.NET配布](https://learn.microsoft.com/en-us/dotnet/core/deploying/)と[SignTool](https://learn.microsoft.com/en-us/windows/win32/seccrypto/signtool)を配布検証の参考とする。[.NETサポート方針](https://dotnet.microsoft.com/en-us/platform/support/policy/dotnet-core)は実装時に再確認し、サポート中安定SDKを固定する。これらは候補APIの根拠であり、本アプリでの実証は別途必要。
