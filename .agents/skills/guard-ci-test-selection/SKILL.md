---
name: guard-ci-test-selection
description: CIのrequired checkを使って失敗を実証・再現する前に必ず参照する。実際のworkflowで対象テストが実行されないまま結果を誤認したため、workflow経路の確認手順を定める。
---

# CIテスト経路の確認

## 背景
- 2026-11-07、CI失敗用fixtureで`test_ai_review_gate_documentation.py`のassertionを狙ったが、PR workflowの実コマンドに含まれておらずCIが成功した。
- 同日、文書テストを含まないコンテナ環境を事前に確認しなかった記録もある。
- 根本原因: テストファイルの存在・unittest discoveryの対象であることだけで、required checkの実行経路に含まれると思い込んだ。

## 守ること
- CI上のテスト結果を使う前に、`.github/workflows/`で対象イベントからrequired statusまでのworkflow、job、実行コマンドを読む。
- jobの`working-directory`、`docker build`のcontext、volume mount、コンテナ内パスを確認し、対象ファイルが実行環境にあるか特定する。
- 対象テストが実行コマンドに明示されるか、指定されたdiscover範囲とpatternに含まれることを確かめる。対象外なら、そのCIを失敗検証に使わない。
- 文書ファイルを読むテストは、実行イメージ内に対象文書が存在するかを確認する。通常アプリイメージに文書がない場合はsetUpでskipし、既存のリポジトリmount付き文書テストstepで同じテストを実行する。
- CI実行後はrun logを読み、意図したテスト名・assertionが実際に実行されたことと、aggregate required checkの結論を確認する。
- 失敗fixtureでは別jobの失敗やskipを区別し、狙った失敗以外があれば作業記録に併記する。

## 作業前チェック
- [ ] `rg -n`でworkflowのevent・required job・テストコマンドを特定した。
- [ ] 対象テスト、作業ディレクトリ、ファイルmountをworkflowとDockerfileから照合した。
- [ ] 対象テストが該当workflow runで実行される根拠を確認した。
- [ ] 文書テストは実行イメージに対象文書があるか確認し、文書がないアプリイメージではskip、既存のmount付き文書テストstepでは実行される。

## 完了前チェック
- [ ] run logで対象test名と期待した結果を読み戻した。
- [ ] required statusの`gh api repos/<owner>/<repo>/commits/<sha>/status`とPRのmerge stateを同一HEADで記録した。
- [ ] 併発した別jobの失敗を隠さず記録した。

## 悪い例 / 良い例
- 悪い: `src/tests/test_ai_review_gate_documentation.py`をdiscover対象だと思い込み、workflowが実行するテストの集合を確認せずCI失敗を期待する。
- 良い: workflowの実コマンドとmountを読み、実行対象のassertionを選び、run logで対象testの失敗を確認する。
