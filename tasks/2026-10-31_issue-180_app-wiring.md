# Issue #180: 取得・世代管理・送信パイプラインのアプリ配線

## 実施内容

- `client/src/ScreenTranslation.Client/App/`に`TranslationSessionHost`(ファサード)、`ITranslationTransport`(`StreamTransportClient`が実装)、`TrackingFrameTransport`を追加。ライフサイクル・取得経路・パイプライン・WSS・オーバーレイを組み立て、対象選択・ROI選択・開始・停止・接続のAPIを提供(UI本体は#98/#99)。
- (a) 開始前に`Prepare`を必須化(除外未確認なら取得セッションも作らず送信しない)。(b) 失効確認ループで`Tick`を駆動。(c) 世代無効化・切断・除外失敗・送信失敗で、経路遮断・送信破棄・基準破棄・表示消去を同期的に実施。(d) `CaptureFrameRouter`が取得fpsで破棄される見込みのフレームを読み出し前に間引く。(e) `WindowsCaptureSession`で配信直前に停止を再確認。(f) `WgcFrameReader`はWinRT Buffer/DataReaderをやめ管理配列へ直接コピー、行詰めなしなら`ToCapturedFrameOwned`で複製なし。
- `WindowsCaptureRuntime.CreateSessionHost`で実WGC工場を使ってホストを組み立てる。
- 文書: development.md対応表、testing.md(配線・Owner実機の通し手順は未実施)。

## 対応要件

REQ-F-002/003/005/006/007、REQ-NF-001/004/008（ACC-01/02/04/06/07/11）

## 未実施

実WGC・実WDA・実サーバー・混在DPI・複数モニター・読み出し削減量の実測(Owner実機手順)。

## 試験結果・mutation

`docker compose -p t180 -f client/compose.test.yml run --build --rm test`の結果とmutation結果はPR本文に記録。
