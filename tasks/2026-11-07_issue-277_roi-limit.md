# Issue #277 ROI上限の要件・契約改訂

## 背景

全画面の複雑背景ではOCR予算を超える測定結果を受け、OwnerはIssue #224でROI上限を幅1280px・高さ300px・384,000画素へ下げる案Bと、要件数値の変更を承認した。OCR時間予算の緩和や、全寸法・全背景での性能保証はこのTaskの対象外とする。追加性能測定は#109で行う。

## 対応内容

- 要件書・設計・受入・通信契約・REQ-ID対応表・開発/運用/調査文書のROI上限を同じ値へ改訂する。
- 契約fixtureを1280×300の境界と幅/高さ超過を拒否する値へ更新する。
- 拡大後画像の4,000,000画素上限、4 MiBの符号化後サイズ上限、OCR時間予算は維持する。
- 要件改訂履歴にOwner承認と#109の未測定範囲を記録する。

## 確認結果

- TDD: 幅1281px・高さ301pxを拒否するfixtureを先に追加し、旧schemaでは3ケースが通ってしまうことを確認した。上限を1280×300へ更新後、契約fixture検証は成功。
- 検証: `ContractFixtureTests.test_both_clients_and_server_agree_on_every_schema_fixture` を実行し、全schema compatibility fixtureを検証。契約JSON全件とOpenAPI YAMLを解析し、OpenAPIの幅1280・高さ300・384,000画素を確認。
- Mutation: frame metadataの幅/高さ、stream resultの幅/高さを各1px緩和する4 mutationと、OpenAPIの最大画素数を384,001へ変える1 mutationをすべて検出。
- `git diff --check` 成功。Docker build/testは空き容量制約のため未実施。CI結果はPR作成後に追記する。
