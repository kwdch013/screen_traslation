# Issue #56 脅威モデル・技術選定ADRの作成

実施日: 2026-10-29。実装担当: Codex。統合先: develop。Issue: [#56](https://github.com/kwdch013/screen_traslation/issues/56)。

## 作業範囲と状態

#55の統合済み要件書と受入計画を正本として、6件の日本語ADR、脅威モデル、全22要件対応、12件の検証課題を作成した。方式は提案として記録し、#58/#59/#60のPoCと #57 の最終設計へ引き渡す。アプリ機能、実機操作、モデル推論、レビュー、mergeは行っていない。

[ADR索引](../docs/v1.0/design/adr/README.md)が比較案・要件ID・問い/担当・判定基準・証跡・未決事項を管理する。[脅威モデル](../docs/v1.0/design/security.md)に資産6種、信頼境界5箇所、脅威14件、対策候補・拒否条件・残余リスクを記録した。

## Claimとブランチ

- #55がClosedでnative dependency解消、#56がready/未Claimであることを確認。進行中 #118 のExpected filesとの競合を確認した。
- origin/developの `e52cd89` からdetached worktreeを用意し、実行ルートを照合してWork Unitを取得した。
- Work Unit: `1827b150-047f-4e17-8579-e4fb6aefa7f5`。Claim helperで獲得後に `task/56-threat-model-adr` を作成した。
- [範囲補足コメント](https://github.com/kwdch013/screen_traslation/issues/56#issuecomment-6500444818)へExpected files外の変更理由と後続Taskの境界を記録した。

## 文書の設計判断

- HTTPS+WSS、WPF/WGC、段階的コア抽出、アプリ内TLSと端末/管理別トークン、単一所有権/世代/最新1枚、固定モデルの明示導入を推奨候補として比較した。
- OS/.NET/Python条件と全数値は要件に従い、未規定の期限やSDKパッチは #57 等で確定する。設計提案の256 bitトークンとTLS下限は要求の既定値と区別した。
- TLSは検証用私設CA、署名は隔離した試験用自己署名コード署名証明書で、購入なしの検証経路を記載した。信頼配布/更新と失効、既存接続停止を検証対象とした。
- 特定マシンの情報を記載せず、接続先・secret・信頼情報を外部設定へ分離する。図は #57/#63 の成果物で、今回の関係は対応表で示した。
- 公式資料を2026-10-29に確認しADRへ根拠を記載した。資料の機能説明と製品の実証を区別した。

## TDDと検証

既存CIが実行する `src/tests/test_v1_documentation.py` に5件を追加した。先にテストを作り、未作成の設計文書/参照による5件の失敗をPython 3.14コンテナで確認した。文書作成後、以下の25件が成功した（skipなし）。

```bash
docker build -f tests/ai_gate/Dockerfile -t screen-issue56-doc-test .
docker run --rm --cpus=2 --memory=512m -v "$PWD:/workspace:ro" -w /workspace screen-issue56-doc-test python -B -m unittest src.tests.test_v1_documentation src.tests.test_web_documentation -v
docker run --rm --cpus=2 --memory=512m -v "$PWD:/workspace:ro" -w /workspace screen-issue56-doc-test sh -c 'pip install --disable-pip-version-check --root-user-action=ignore ruff==0.16.1 >/dev/null && ruff check --no-cache src/tests/test_v1_documentation.py'
git diff --check
```

RuffはAll checks passed、差分の空白検査も成功。Ruff初回は読み取り専用ソースへのキャッシュ作成で失敗したため、`--no-cache`を付けて成功を確認した。

追加テストは全要件の判断先、ADRの比較/検証/未実施状態、脅威の境界/要件/対策/担当/拒否条件、Q参照、相対リンク、未知の要件/受入ID、機器固有情報の混入、既存ガイドからの参照を検証する。文書テストは実機動作・脅威対策の実装・性能/品質合格を証明しない。

## Expected files以外の変更

- 現行仕様/開発者/利用者ガイド: 受入条件の関連文書更新として、候補設計と脅威モデルへの参照を追加した。現行Webの契約を維持する。
- ロードマップ: 要件ID対応表への参照を追加し、#55の記録を統合済みの状態へ更新した。
- 文書テストと本作業記録: ユーザー指定のTDD/証跡のため追加した。#118担当のdevelopment.mdとCI設定は変更しない。

## 残件とOwner判断

PoC・TLS/資格情報の具体期限・契約・SDKパッチ・最終採否は担当Taskへ引き渡した。現在Owner判断を必要とする要求変更や購入はない。不達時には影響要件ID・原因・測定値・代替案をOwnerへ提示する。

ユーザー指定どおりPR作成で停止し、独立レビュー依頼・承認・merge・Issue Closeは行わない。PRはbase=develop、Closes #56とWork Unit markerを付ける。完成時の引き継ぎは担当worktreeのgit管理外 `tmp/handover.md` に残す。
