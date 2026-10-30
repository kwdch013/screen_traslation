# Issue #64 共通契約fixtureと両言語の互換性テスト

## 実施内容

- API、binary message境界、座標/DPI/ROI、session遷移と結果採用の正常・異常fixtureを用意した。
- Python 3.14でJSON Schema Draft 2020-12を検証し、同じ互換性fixtureをC# validatorでも受理/拒否と理由まで確認するテストを追加した。
- API設計書に要件ID対応、正本、検証コマンド、テストの対象外を記載した。
- 既存のbinary境界テストを、magic・各長さ・宣言payload・総長の全条件で判定するよう更新した。
- 前任作業に残っていたPythonテストの不正インデントを除去し、mistake logへ根本原因と対策を記録した。

## 検証結果

| 検証 | 結果 |
|---|---|
| `docker build -t app:ci .` | 成功 |
| マウントなし `src/tests` 回帰 | 300件成功、66件skip |
| 契約・設計文書マウント付き `src/tests` 回帰 | 300件成功、55件skip |
| server compose test | 7件成功 |
| client compose test | 契約4件成功、Core 1件成功 |
| `mypy src` | 成功、78ファイル |
| `mypy --platform win32 src` | 成功、78ファイル |
| `ruff check src scripts tests/ai_gate server/tests/contracts` | 成功 |

## コミット

- `368fe76 test: 共通契約fixtureと両言語の互換性テストを追加`
- 後続コミットに検証runner・文書・作業記録を含める。

## 制約

fixture検証は実機のTLS、画像decoder、性能、座標取得を検証しない。これらは後続Issueの対象。
