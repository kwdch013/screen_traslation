# 設定・辞書APIの追加

## 背景

ウェブアプリ化の第4段階として、tkinterでのみ編集できた`PipelineConfig`と用語辞書をブラウザから読み書きする土台が必要になった。Issue #10の要件に基づき、UIは対象外としてローカルWeb APIと永続化を追加した。

## 実装

- `GET /api/config`と`PUT /api/config`を追加した。
  - 公開項目を明示し、ログパス、LLM接続先、対象領域、内部バックエンド等を応答・更新対象から除外した。
  - `PipelineConfig` / `OverlayStyle`の検証エラーをHTTP 400で返す。
  - 保存後の設定を`WebAppService`の次回`start`で参照し、応答を`applied: next_start`とした。
- `GET /api/glossary`、`POST /api/glossary`、`DELETE /api/glossary/{source}`を追加した。
  - 空文字をHTTP 400、重複をHTTP 409、存在しない削除をHTTP 404とした。
  - 登録・削除後に実行中パイプラインの`TranslationCache`を失効し、次の翻訳から反映する。
- 設定と辞書の保存を、同一ディレクトリの一時ファイル作成と`os.replace`による原子的置換へ変更した。
- `Glossary`と`TranslationCache`をロックで保護し、APIスレッドとパイプラインスレッドの同時アクセスに対応した。
- 共通Hostミドルウェアが新APIにも適用される構成を維持し、変更系ルートで既存のOrigin検証を実行した。
- Web起動時にCLIで指定された`--config`と`--glossary`のパスを`WebAppService`へ渡し、既存のデスクトップアプリと`--add-term`の経路は変更しなかった。

## テスト

### Red

`src/tests/test_web_settings_api.py`を先に追加し、次を実行した。

```text
PYTHONPATH=src .venv/bin/python -m unittest src.tests.test_web_settings_api
Ran 8 tests: FAILED (errors=8)
WebAppService.__init__() got an unexpected keyword argument 'config_path'
```

未実装の設定・辞書パスおよびAPI契約により失敗することを確認した。

### Green

実装後に同じ8テストを再実行し、全件成功した。設定の公開範囲、次回start反映、不正設定時のファイル不変、辞書CRUDと永続化、キャッシュ失効、Host / Origin拒否を検証した。

設定・辞書・パイプライン・WebAppService・Web起動をまとめた関連テスト41件、および環境依存モジュールを除く回帰テスト126件が成功した。`compileall`と`git diff --check`も成功した。

このsandboxでは既存の`TestClient`テストが応答待ちで停止することを、既存の制御APIテスト単体でも再現した。ソケットを使う既存テストは`PermissionError: Operation not permitted`、Dockerはデーモン接続権限拒否となった。venvに`ruff`がなく、`requirements-dev.txt`からの導入もネットワーク名前解決制限で失敗したため、コンテナ内の全テストと`ruff check src`は依頼者環境での最終確認が必要である。

## 対象外

- 設定・辞書のReact UI
- tkinterの撤去
- SSEおよび制御APIの仕様変更
- 公開設定項目の全面的な再設計（段階9で実施）
