# Issue #277 ROI上限の要件・契約改訂

## 背景

全画面の複雑背景ではOCR予算を超える測定結果を受け、OwnerはIssue #224でROI上限を幅1280px・高さ300px・384,000画素へ下げる案Bと、要件数値の変更を承認した。OCR時間予算の緩和や、全寸法・全背景での性能保証はこのTaskの対象外とする。追加性能測定は#109で行う。

## 対応内容

- 要件書・設計・受入・通信契約・REQ-ID対応表・開発/運用/調査文書のROI上限を同じ値へ改訂する。
- 契約fixtureを1280×300の境界と幅/高さ超過を拒否する値へ更新する。
- 拡大後画像の4,000,000画素上限、4 MiBの符号化後サイズ上限、OCR時間予算は維持する。
- 要件改訂履歴にOwner承認と#109の未測定範囲を記録する。

## 確認結果

- TDD/CI失敗の原因: 初回CIの互換性fixtureが新しい幅・高さ超過例を拒否するようになった一方、C#の`TransportProtocol`と`ContractValidator`は1920×1080・2,073,600画素を許容し、Client.Tests 2件とContracts.Tests 1件が失敗した。
- 修正: C#通信層と契約fixture validatorの幅・高さ・画素上限を1280・300・384,000へ同期し、通信境界テストの有効な最大寸法を1280×300へ変更。UI選択範囲とサーバー受理処理はそれぞれ後続T-c / T-bの対象として維持する。
- 2回目CIの追加失敗: 新上限で受信結果を検証すると、C#単体テストの共有fixtureとOverlayテストに残っていた高さ320pxの結果が無効になるため、依存するテストfixtureの高さを300pxに揃える。Python回帰テストではcompatibility.jsonがcases objectである点に合わせる。
- OpenAPIの幅・高さ・画素上限、JSON Schemaの幅/高さmaximum、互換性fixtureの上限・超過例を同時に確認する回帰テストを追加。
- Mutation: frame metadata width/height、stream result width/height、OpenAPI画素上限の削除、JSON Schema maximum削除の6種類を静的契約チェックで検出。
- `python3 -B -m py_compile src/tests/test_api_contract_schemas.py`、契約JSONの標準ライブラリparse、`git diff --check`は成功。
- `python3 -B -m unittest src.tests.test_api_contract_schemas -v`は実行したが、ホストに`jsonschema`が無いため全テストが依存import errorで終了。dotnetも未導入。Docker build/testは禁止条件により未実施し、C#と契約統合検証はpush後のCIで確認する。
- CI結果: 初回はC#契約validatorの旧上限で`contracts`と`windows-client`が失敗。2回目は新たなvalidator境界に対し既存C#結果fixtureが高さ320pxを使っていたためClient.Testsが失敗し、Python回帰テストはcompatibility.jsonのcasesを取り出さず反復して失敗。修正後の結果を確認して更新する。
- `1920x1080` / `2,073,600` の残存箇所はROI上限変更前の測定履歴、OCR前処理測定、画面・モニター例、または後続T-b/T-cの実装対象。拡大後画像の4,000,000画素上限は変更していない。
