# リポジトリガイドライン

- ファイルは日本語で記載します。今後このファイルへ追記・更新する場合も、原則として日本語で記載してください。
- 要件の解釈が複数可能な場合は聞き返してください。

## ルール
- 特に指示がない場合と、一時的なファイルを除き、コンテナ化して実装を行うこと
- コンテキストがclearされている場合、tasks/ の内容を確認し、前回作業を引き継いでください。

## テスト
- コーディングと同時にテストも行う、テスト駆動型開発を行うこと


## Git管理
- 作業内容を、tasks/ にmd形式で記載すること
- 一連の作業が終わったら、prefixと、日本語のコミットメッセージをつけて、コミット&プッシュを行うこと


## バージョン
- 特に指定がない限り、新規でコンテナを作成する際にはpython は3.14を使用すること

## コンテナ
- "docker-compose" のコマンドは用いず、"docker compose" を用いること

## その他
- 作業が完了したら、コンテキスト削減のため、/clearを促すこと

# 基本のディレクトリ構造
```
{repo}
├ docs/ 
├ client/                  # v1.0 Windowsクライアント (.NET 10)
│ ├ src/                   # CoreとWindows UI
│ └ tests/                 # Linuxで実行できるCoreテスト
├ server/                  # v1.0 Linuxサーバー (Python 3.14)
│ ├ src/
│ └ tests/
├ contracts/               # client/server共通契約
├ src/
| ├ app/
| └ tests/
├ frontend/                # 既存Web版。v1.0受入までは維持
├ tasks/
├ docker-compose.yml
├ Dockerfile
├ .gitignore
├ .env
├ .env.example
├ README.md
└ requirements.txt
```

## Work Unit・Claim・独立AIレビュー

- 既定ブランチは `develop`。実装とTask/Phase統合はdevelop（または必要なPhase branch）で行い、mainはMilestone内の全Issue完了とdevelop上のシナリオ試験・ユーザー受入の完了後だけ更新する。
- 1 Task = 1 Issue = 1 branch = 1 PR。`origin/develop`（必要時はPhase）から作る。着手前にIssueのnative dependencyとExpected files競合を確認する。
- 専用worktreeで `git rev-parse --show-toplevel` を確認後、`python3 scripts/ai-work-unit.py` でWork Unitを取得する。同じworktreeの親・子エージェントは同じID、別worktreeは別ID。保存IDをコピー・手動編集しない。
- `git config core.hooksPath .githooks` でhookを有効にする。commitには現在のWork Unitの `AI-Work-Unit: <uuid>` が自動追記され、未記録・不正trailerのpushは拒否される。
- ClaimはOpen・`issue/ready`・依存解消済み・有効Claimなしを再確認して投稿する。GitHubのComment作成時刻、同時刻ならComment IDが最小のClaimを勝者とし、勝者だけが `issue/in-progress` と `worker/claimed` を設定する。停止中Claimを自動失効させない。
- PR本文の先頭に `<!-- ai-pr-work-unit: <uuid> -->` を1つと `Closes #<Issue番号>` を記録する。実装完了時はIssueを `issue/review-required`、PRを `pr/review-required` とし、merge前にIssueをCloseしない。
- PR作成者・全commit（squashを含む）のContributor Work Unitは自己承認できない。実装と別のエージェント・別worktreeがIssueとPRをセットで確認し、最新HEAD SHA付きの承認Commentを本人が投稿する。レビュー中にコードを変更しない。
- `pr/approved` だけでmergeしない。最新HEADへの構造化承認・Contributor除外・linked Issue状態・CI・未解決conversationを確認する。新commit後は再レビューする。
- Task / Phase PRはsquashでdevelopへ統合し、PR本文の `Closes #N` によりIssueを自動closeする。squash commitには全Contributorのtrailerを残す。
- mainへのリリースPRはMilestone内の全Issue完了とdevelop上のシナリオ試験・ユーザー受入完了後に限り作成し、`develop → main` をmerge commitで統合する。ゲート導入を理由に先行リリースしない。
- ゲートはdefault branch上の信頼済みscriptだけを実行する。未発行checkをRulesetへ追加しない。初回導入・有効化とコマンドは [開発手順](docs/v1.0/development.md#work-unitclaim独立レビューの操作) を参照する。
