# Issue #160: AI Review Gateの承認待ちをpendingとして扱う

## 背景
独立承認のないPRでcommit status `AI Review Gate`がfailureとなる状態を直し、承認待ちと実際の違反を分ける。GitHub Actionsの実行ポリシー変更とUbuntu runner移行も調査し、PR由来コードを権限付きで動かさない。

## 実施内容
- 判定を`PASS` / `PENDING` / `FAIL`に整理。未承認はcommit statusを説明「独立レビュー待ち」のpendingとし、CLI終了コード0で`PENDING`を表示する。違反のみfailure・終了コード1。API/引数エラーは終了コード2。
- 構造化判断を作成日時・Comment ID順で評価し、最新の変更要求、自己承認、古いHEAD、PR marker/commit trailer不備、Issue状態不整合、`pr/block`をFAILにする。
- workflow job `gate`はPENDINGでも正常終了する。commit statusはpendingのままなのでrequired checkによるmerge拒否を維持する。CI成功は別のrequired checkとして扱う。
- `pull_request_target`は維持し、default branchの信頼済みscriptだけを実行する。GitHub Actions policyを`.github/workflows/ai-review-gate.yml`に限定し、現行triggerだけを許可するリポジトリpolicyを作成・読み戻した (ID `10134`, active)。PR側コードやartifactは取得・実行しない。
- runnerは`ubuntu-24.04`に固定。公式告知によるUbuntu 26.04への`ubuntu-latest`段階移行期間に当たるため、26.04は別途検証後に移行する。
- `docs/v1.0/development.md`と本作業記録を更新。

## GitHub公式資料
- Workflow execution protections: https://github.blog/changelog/2026-09-17-workflow-execution-protections-in-github-actions-generally-available/
- Securely using pull_request_target: https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target
- Governing workflow execution: https://docs.github.com/en/actions/how-tos/administer/control-workflow-execution
- Actions policy REST API: https://docs.github.com/en/rest/actions/policies
- Ubuntu 26 migration: https://github.blog/changelog/2026-09-17-ubuntu-26-generally-available-and-latest-migration/

## 検証結果
- TDD: 判定・workflowテストを先に追加し、未実装時の失敗を確認。
- `docker build -f tests/ai_gate/Dockerfile -t ai-gate-test:ci .` とマウント付き`python -B -m unittest discover -s tests/ai_gate`: 71件成功。
- `docker build -t app:ci . && docker run --rm -e PYTHONPATH=/app/src app:ci python -B -m unittest discover -s src/tests`: 306件成功、72件skip。
- `docker run --rm --cpus=2 --memory=512m -v "$PWD:/workspace:ro" -w /workspace ai-gate-test:ci python -B -m unittest src.tests.test_v1_documentation src.tests.test_web_documentation src.tests.test_desktop_removal`: 41件成功。
- `docker run --rm --cpus=2 --memory=512m -v "$PWD:/workspace:ro" -w /workspace app:ci mypy --cache-dir=/tmp/mypy-cache src`: 79 source files成功。
- `docker run --rm --cpus=2 --memory=512m -v "$PWD:/workspace:ro" -w /workspace app:ci ruff check --no-cache src scripts tests/ai_gate`: All checks passed。
- `git diff --check`: 成功。

## 状態
- Issue: https://github.com/kwdch013/screen_traslation/issues/160
- branch: `task/160-gate-pending-state`
- PR: 作成後に追記。
- 独立レビューとmergeは未実施。
