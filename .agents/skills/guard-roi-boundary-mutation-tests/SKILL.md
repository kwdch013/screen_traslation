---
name: guard-roi-boundary-mutation-tests
description: ROIやサイズ上限の境界値テストを作成・mutation検証する前に参照する。受理境界を下げたmutationが未捕捉の例外errorとなり、検出状況を誤認する再発を防ぐ。
---

# ROI境界テストのmutation確認

## 背景
- 2026-11-07、上限を1下げるmutationで`assertRaises`を使った境界テストが例外errorになり、assertion失敗として数えられなかった。
- 同じ根本原因がROI validatorとOCR engineの両方で発生した。

## 守ること
- 受理/拒否の期待値は、検証関数の例外を真偽値へ変換して`assertEqual(actual, expected)`で比較する。境界を1下げたときもテストerrorではなくassertion failureになることを確認する。
- 幅・高さ・総画素数それぞれに対して、上限値と±1のケースを含める。幅・高さの独立上限を検査する例では、もう片方の値を十分小さくし、画素上限に先に達しないようにする。
- 上限定数を契約(OpenAPI/Schema/fixture)と照合し、コードの値と契約の値が一緒に変わるmutationも検出する。
- Mutationとして数えるのは、対象テストが実行され、期待したassertion failureが出た場合だけとする。ImportError、tests 0件、予期しない例外は検出成功とみなさない。

## 作業前チェック
- [ ] 最大境界の受理と各上限の超過拒否を確認するテストがある。
- [ ] 幅/高さを個別に検証する境界例は、面積上限の影響を受けない寸法にしている。

## 完了前チェック
- [ ] 旧上限・各寸法の±1・画素上限のmutationを実行した。
- [ ] すべて対象テストのassertion failureで検出され、最後に無mutationのテストが成功した。
