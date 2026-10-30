# ADR-0001 通信方式の候補

## 状態

2026-10-30、**設計採用**。HTTPS制御/設定 + 1本のWSS双方向ストリームを採用する。製品相互運用・切断・遅延の実証は未実施で、契約schemaは #62/#64 が確定する。[索引・検証課題](README.md) / [基本・詳細設計](../architecture.md) / [脅威モデル](../security.md)。

## 対象要件

REQ-F-003、REQ-F-006、REQ-F-008、REQ-F-009、REQ-F-010、REQ-NF-001、REQ-NF-004、REQ-NF-006、REQ-NF-009。

## 背景

WindowsからLAN上のLinuxへROI画像を送り、状態・訳文・領域を返す。既存Web版のPOST/SSEは比較材料であり、新版へそのまま転用する契約ではない。最大5 fps、同時処理1、最新待機1枚、切断と所有権を一貫して扱う必要がある。

## 比較

| 候補 | 利点 | 制約・今回の判断 |
| --- | --- | --- |
| HTTPS制御/設定 + WSS画像/結果 | 双方向の切断を同じ接続に結び付け、バイナリ画像を送れる | キュー/フラグメント/メッセージ長とUpgrade認証の設計が必要。推奨候補 |
| HTTPS画像POST + SSE結果 + HTTPS制御 | 現行知見を使え、各要求の拒否が明確 | 複数経路のセッション・失効・再接続を揃える必要。代替候補 |
| gRPC双方向ストリーム | 型付け契約と双方向通信 | HTTP/2と両言語生成系の運用が増える。本規模では優先しない |

## 採用方式

HTTPSで接続状態・開始/停止・設定/辞書等を扱い、認証済みの単一WSSで画像と結果/状態を双方向に運ぶ。WSS binary message内にUTF-8 JSONメタデータとPNG/JPEG bytesを含め、text messageは状態/結果に使う。routeは`/api/v1/stream`、HTTPS routeと入出力境界は[基本・詳細設計](../architecture.md#通信api詳細)で定める。具体schema/field長/frame fixtureは #62/#64 の`contracts/`が正本となる。

Issue #72の入口骨格はStarlette `1.10.0`とUvicorn `0.52.4`を使用し、両依存はBSD-3-Clauseとして2026-10-30にPyPIで確認した。UvicornはWebSocket実装`websockets==15.0.1`を使い、message上限を4,198,408 bytes、同時接続/要求を128に制限する。TLS contextを直接Uvicornへ渡し、proxy headerを無効化する。開始/停止、結果配信、設定/辞書APIの処理本体はこの入口骨格に含めない。

全経路にTLS 1.2以上と端末認証を適用する。WSSはUpgrade前に認証し、資格情報をURL/queryへ載せずAuthorization headerで渡す。health/readyも例外にしない。管理要求は別権限とし、通信接続の成立だけで画面取得を開始しない。WebSocketのmessage上限、ping間隔、実装ライブラリ別のUpgrade制御は#62/#74/#79/#89で実装前に照合する。

## 検証と確定担当

Q-01/Q-04/Q-05を #57/#62/#64 で設計し、#72/#74/#79/#89/#108で認証失敗・切断・遅延・同時開始・所有権の試験を行う。#57は2方式を同じ上限/失効条件で比較し、代替へ変更する場合も脅威表とADRを更新する。ACC-04/ACC-05/ACC-08/ACC-11を判定先とする。

## 影響

WSS導入だけでは入力上限やバックプレッシャーを保証しない。送信待ち、受信メッセージ、展開後画素数、処理待ちを別々に制限する。切断後は表示を消し、明示開始で新セッションを作る。HTTP/SSEの採否を変えても[所有権・世代](0005-session-lifecycle.md)は維持する。既存Web版のループバック制約は維持する。

## 根拠

2026-10-29確認: [Starlette WebSocket API](https://www.starlette.io/websockets/)はバイナリ送受信とaccept前の拒否を提供する。[Starlette認証](https://www.starlette.io/authentication/)にはWebSocketに固有の制約があるため、HTTP経路と同じ拒否表示になると仮定しない。上記の推奨は要求からの設計判断であり、両言語での製品動作の根拠ではない。
