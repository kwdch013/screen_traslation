# Issue #210: セッション取得・解放のHTTPSクライアント

## 実施内容

- `client/src/ScreenTranslation.Client/Api/`を追加。
  - `ControlApiClient`: 制御API(`/api/v1/...`)を呼ぶ認証付きHTTPSクライアントの共通部分(設定・辞書の編集UI #99 が再利用する)。接続先は`ConnectionSettings`(HTTPSのみ)、端末資格情報は呼び出しごとに保護保存から読む。TLSはOSの検証に従い、証明書SHA-256指紋があれば追加で固定(WSSと同じ`ServerCertificatePin`)。検証無効化・信頼ストア変更・リダイレクト追従・Cookieを持たない。要求ごとの期限、応答本文64 KiB上限。失敗は`ControlApiException`(`ControlApiFailure`の分類。サーバーの文言・URL・内部例外を持たない)。
  - `ControlApiErrorBody`: `error.schema.json`に適合するエラー本文だけを解釈(message・correlation_idの中身は使わない)。
  - `SessionApiClient`(`ISessionGrantProvider`): `POST /api/v1/sessions`(201・session.schema適合・generation=1だけ受理)と`DELETE`(204、404は解放済みとして成功)。理由別の日本語(`SessionGrantMessages`)を`SessionGrantException.Kind`付きで通知。
- `SessionGrantFailure`(OperationPorts.cs)を追加し、`SessionGrantException`に`Kind`を持たせた(文言は従来どおり`Message`)。
- WSSの開き直し: サーバーはWSSのUpgrade時にsessionを結び付ける(`app.py`の`active_for_owner`)。既存の「接続→開始(POST)」順ではPOST後のsessionが結び付かず、フレームが1008で拒否される。`ITranslationTransport.ReopenStreamAsync`(`StreamTransportClient`は新接続を確立してから入れ替え、受信ループは入れ替えを切断として扱わない)を追加し、`TranslationSessionHost.StartAsync`がsession有効化の前に呼ぶ。
- 解放の前の結び付け解除: サーバーはDELETEで結び付いたWSSを閉じるため、閉じられて「切断」に見え状態が未接続になる(実サーバー結合で確認)。`ISessionOperations.PrepareForReleaseAsync`/`ITranslationTransport.ExpectServerClose`を追加し、`OperationsViewModel`が解放(DELETE)の前に「想定内の切断」を準備、受信ループは10秒以内の1回の切断を通知せず未割当のWSSへつなぎ直す(結び付いた状態で先に開き直すとサーバーが同じsessionへ結び付けてしまうため、DELETEの後につなぐ)。新sessionの世代は1から始める(従来の通し番号を契約に合わせて変更)。
- `OperationsViewModel`: 終了時に、待たずに始めた解放の完了を待ってから`IDisposable`の`grants`を片付ける。
- Windows: `UnavailableSessionGrantProvider`を削除し、`MainWindow.Operations.cs`が保存済み接続設定から`SessionApiClient`を組み立てる。
- サーバー(最小): WSSのsubprotocol `screen-translation.v1`(契約・クライアントが必須とする)をサーバーが選択していなかった。実サーバー結合で判明。クライアントが提示したときだけ選択する1箇所を修正(`app.py`)し、`server/tests/test_stream_subprotocol.py`を追加。Issue本文は「サーバー側の変更」を対象外としているが、これが無いと実サーバーに接続できない(要レビュー判断)。
- 実サーバー結合試験: `client/compose.real-server.yml`(serverイメージの本物のアプリ+`client/tests/real-server/serve.py`、OCR・翻訳エンジンだけ固定の代替)と`RealServerTests`(Category=RealServerIntegration)。CIの`contracts`ジョブに追加。
- 文書: testing.md・operations.md・development.md(対応表)・api.md。

## 判断

- 文言はサーバーのmessageを使わず固定文(機微情報が本文に入っていても表示・ログに出さない)。ステータスとcodeが食い違う409/503は「使用中」「準備中」と断定しない。
- 失敗の例外には内部例外を持たせない(HttpRequestExceptionのメッセージがURL=session_idを含み得るため)。
- 証明書指紋の固定はWSS既存の仕様(OS検証も通ることが前提)をそのまま共有。自己署名証明書を指紋だけで信頼する方式ではない(要レビュー判断・既存仕様)。

## 対応要件

REQ-F-006 / REQ-F-007、REQ-NF-003、REQ-NF-004（ACC-01 / ACC-02 / ACC-05 / ACC-08）

## 未実施

Windows実機(DPAPI保存の資格情報での実接続、実Linuxサーバーとの通し)はOwner手順。

## 試験結果・mutation

PR本文に記録。
