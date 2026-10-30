# Issue #62 制御・フレーム・翻訳結果・設定API契約

## 目的

HTTPS制御/設定APIと単一WSS、binary画像フレーム、翻訳結果、認証・revision競合、サイズ/文字上限、共通エラーを機械検証可能な契約として追加する。#63の画像座標とsession/generation/frame/revision状態定義はPR #139を読み、重複作成せず参照する。

## 変更

- `contracts/openapi.yaml`: OpenAPI 3.1.0、認証付きhealth/ready/session/settings/glossary/credential APIとWSS route。
- `contracts/schemas/`: session/settings/glossary/frame metadata/stream/error JSON Schema。
- `contracts/fixtures/`: 正常な制御・設定・binary metadata・state/result/error例とHTTP異常例。
- `contracts/README.md`: binary header、サイズ/文字制約、認証/role、revision競合、error/status/close code、互換版・検証方法。
- `docs/v1.0/design/api.md`: 呼出し順、API動作、失敗時、要件/設計対応。#63の相対契約リンクを保持し、未マージ・未確定部分は#63を正本と明記。
- `src/tests/test_api_contract_schemas.py`: fixture/schema検証。通常`app:ci`に契約docsが無い場合はskipし、mount付き実行で回帰を維持。

## TDD / 検証記録

- テスト先行: `contracts/README.md`だけを一時作成して新テストを実行し、schema/fixture未作成による失敗を確認後、一時ファイルを削除。
- 契約fixture unittest: `PYTHONPATH=src python -B -m unittest src.tests.test_api_contract_schemas -v` — 成功 (6件)。
- OpenAPI lint: Node `24.11.1-alpine` + `@redocly/cli@1.34.5` — 最終版を検証しschema valid。ライセンス情報未指定の警告1件のみ。WSSはHTTP 101 handshakeを正確に記録し、偽の2xx応答は加えない。
- PR #139は作業中にmergeされたため、`origin/develop`の`6276b65`をfast-forwardで取り込み、#63契約リンクを含む状態で最終検証する。
- `docker build -t app:ci .` — 成功。続く指定のmountなしunittestは295件成功、61件skip (文書/環境依存テストを含む)。
- `docker build -f tests/ai_gate/Dockerfile -t screen-v1-doc-test .` — 成功。mount付き`test_api_contract_schemas`, `test_v1_documentation`, `test_web_documentation`は43件成功。
- `docker run --rm app:ci mypy src` / `mypy --platform win32 src` — 各78 source files、問題なし。
- `docker run --rm app:ci ruff check src` — All checks passed。
- `git diff --check` — 成功。#63との相対リンクとsession/generation/frame/revision・座標語彙を契約テストで確認。
- 最終変更後の再実行: `app:ci` mountなしunittest 297件成功 / 63件skip、mount付き文書回帰44件成功、両mypy 78 source files成功、ruff成功、OpenAPI lint成功。

## PR #140 変更要求への対応

- TDD Red: 独立validatorを使うようテストを書き換えて実行し、通常環境に`jsonschema`が無いため9件すべてが失敗することを確認。
- binary message上限を8-byte header + 4,096-byte metadata + 4,194,304-byte画像payload = 4,198,408 bytesへ統一。上限ちょうどと+1 byteの境界fixtureを追加し、fixture・README・OpenAPI・API設計の値をテスト。
- `jsonschema`のDraft 2020-12 validatorとFormatChecker、`referencing`のローカルRegistryで全schemaの`check_schema`と全正常fixtureの検証を行う。UUIDの不正値、寸法超過、未知fieldが拒否されるネガティブテストを追加。
- `requirements-dev.txt`へ検証依存を固定。Dockerfileは既に開発依存をインストールし、CIはこのDockerfileを利用。契約文書が無い通常イメージはvalidator import前にskipし、文書mount時は検証をskipしない。
- CIへapp:ciでのmount付きschema検証stepを追加。`tests/ai_gate/Dockerfile`はschema testを実行しない標準ライブラリ専用テストのため追加依存は不要。
- 最終検証: 指定Docker build成功、mountなし全体回帰300件成功/66件skip、mount付き契約schema 10件成功/skipなし、mypy Linux/Windows各78 source files成功、ruff成功。
- 依存無しのPython 3.14 imageで契約文書をmountしない場合、schema test 10件がimport errorなしでskipすることを確認。
- mount付き全src/tests実行では、修正前のschema例外参照エラーに加え、frontend/distがmountから見えないことによるWeb testの503と並列file-lock timeoutが発生。PR本文では該当回帰を文書・schemaテストのCI対象範囲として記載する。

## Issue/PR

- Base / Merge target: `develop`
- Branch: `task/62-control-frame-settings-api`
- Claim: Work Unit `75b43ad7-624b-4908-865f-4e62d7c22964`、Claim ID `46992642-dd4c-4c29-ba18-7c3f756c6360`
- Issue #62を完了状態へ変更していない。PR作成後に`issue/review-required` / `pr/review-required`へ遷移する。
