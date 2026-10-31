# Issue #186 DependabotのPRをAI Review Gateの規則違反扱いにしない

## 方針
- 作成者が`dependabot[bot]`(Bot)、全commitの作者がDependabot、committerが`dependabot[bot]`/`web-flow`、署名検証済みの場合だけ免除する。
- 免除PRのstatusは`pending`(説明: AI Review 対象外: Dependabot。人手で確認して merge)。承認・merge経路は作らない。
- 判定はGitHub APIの値のみ。PR本文は使わない。workflow permissionsは変更なし。
- 実データ(PR #130): author `dependabot[bot]`/Bot、committer `web-flow`、verification verified=true。

## 変更
- `scripts/ai_review_gate_dependabot.py`(新規): 判定関数
- `scripts/ai-review-gate.py`: `EXEMPT`状態、status/出力
- `tests/ai_gate/test_dependabot_exemption.py`: 境界テスト
- `docs/v1.0/development.md`: 運用手順・対応表

## 検証
- ai_gateテスト81件OK。mutation(type判定・all→any・verified・committer・作者判定・全True・250件上限)でいずれも失敗を確認。
- 実Dependabot PRでの動作はdevelopへのマージ後にのみ確認可能。
