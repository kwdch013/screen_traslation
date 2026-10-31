# Issue #83 設定・用語辞書ストア

## 実施内容

- 契約のschema_version=1、初期revision=1、settingsのcapture_fps既定値2とglossary entriesに沿う固定名JSONストアを追加した。
- 旧Web版を変更せず、既存`app.atomic_file`と`app.file_lock`を新serverの保存境界から再利用した。
- 更新値検証、revisionの比較と加算、409相当の`RevisionConflict`（現在revisionと現在値を保持）、破損ファイルの拒否を実装した。
- 読み込み時に固定byte上限までのbounded readを行い、超過ファイルはJSON展開前に破損として拒否する。上限はsettingsの固定項目とuint64 revisionに対する1,024 byte、glossaryの最大1,000件・各128文字に対する`1000 * (2 * 128 * 6 + 128) + 1024` byte（JSON制御文字の最大6 byte表現と項目構造の余白）とした。
- Issue #83 Expected files外で必要になった運用記録として、テスト起動ミスを`.agents/mistake-log.md`に残し、再発防止guardをCodex/Claude共通配置へ追加した。

## TDD・検証

- 先に設定/辞書ストアの往復、無効値、破損JSON、原子的保存失敗、別プロセス同時更新のテストを追加し、保存層未実装による失敗を確認してから実装した。
- ファイルbyte上限の境界（上限ちょうどは読取可能、上限+1は拒否）と、上限の100倍の疎ファイルが上限+1 byteだけ読み込まれて拒否されることを、settings / glossaryの両方に実装前追加した。サイズ超過時は取得・更新の双方で`StorageCorruptionError`となり、ファイル内容とrevisionを保持する。
- `docker compose -p issue83 -f server/compose.test.yml run --build --rm test python -m unittest discover -s tests -p 'test_*_store.py'`: 17件成功。
- `docker compose -p issue83 -f server/compose.test.yml run --build --rm test python -m unittest discover -s tests`: 31件成功。
- `docker build -t app:ci .`後、通常イメージと`src/` read-only mount付き回帰を実行: 各306件成功、72件skip。
- `mypy src` / `mypy --platform win32 src`: 各79 source files成功。server storage mypy (legacy `src`をMYPYPATHに指定、通常/`win32`): 各4 source files成功。ruff: 成功。

## 仕様との対応

- OpenAPI / settings・glossary schemaに記載済みの初期値、revision、項目上限、古いrevisionの409相当処理に沿う。契約・API・設計文書の変更は不要。
- 旧Web版の設定・辞書ファイル形式と保存経路は変更していない。
