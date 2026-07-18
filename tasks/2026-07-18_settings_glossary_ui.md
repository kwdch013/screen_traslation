# 2026-07-18 設定・辞書UI

## 対応 Issue

- Issue #16「ウェブアプリ化(7/9): 設定・辞書UIを実装する」
- 作業ブランチ: `feat/settings-glossary-ui`
- 依頼どおりブランチ変更、コミット、プッシュは実施しない。

## 要件整理

- 設定タブを`GET /api/config`の公開フィールドすべてに接続し、編集内容を`PUT /api/config`で保存する。
- 数値範囲をブラウザ側でも検証し、APIの400応答に含まれるメッセージを表示する。
- 保存失敗時は入力途中の値を保持し、成功後は設定を再取得する。
- `applied: next_start`を「次回開始から反映」として明示する。
- 辞書一覧を取得し、空文字・重複エラーを表示しながら登録・確認付き削除を行う。
- 辞書の登録・削除後は一覧を再取得する。

## TDD記録

### Red

`frontend/src/SettingsPanel.test.tsx`を先に追加し、設定表示、数値検証、400エラー時の入力保持、保存後再取得、`next_start`表示、辞書の空文字・409、登録・削除後再取得をテストした。

```text
npx vitest run src/SettingsPanel.test.tsx
Test Files  1 failed (1)
Tests       no tests
Failed to resolve import "./SettingsPanel"
```

未実装の`SettingsPanel`を解決できず失敗することを確認した。

### Green

- `api.ts`へ設定・辞書APIの型、安全な応答検証、400/409/404の`detail`抽出を追加した。
- 設定の表示・入力・検証・保存・再取得を`ConfigEditor.tsx`へ分離した。
- API公開設定を文字列の編集状態として保持し、保存成功時だけ再取得値へ置き換えることで、失敗時の入力を維持した。
- 辞書の一覧・登録・確認付き削除・再取得を`GlossaryEditor.tsx`へ分離した。
- 設定タブを初めて開いた時だけ設定UIをマウントし、既存タブの初期API呼び出しを増やさないようにした。
- 設定・辞書UIのスタイルを`SettingsPanel.css`へ分離した。
- タブ接続の回帰テストを`App.test.tsx`へ追加した。

実装直後の対象テストは7件、削除404の回帰テストとタブ接続テストを含む追加テスト9件すべてが成功した。

## ドキュメント

- `docs/user_guide.md`へ、設定保存、次回開始時の反映、エラー時の入力保持、辞書登録・削除の操作を追記した。

## 検証結果

- `npx vitest run`: 6ファイル、47件成功。
- `npm run lint`: 成功。
- `npm run build`: 成功。
- `docker compose run --rm app python -m unittest discover -s src/tests`: 209件実行、失敗0、環境依存6件skip。
- `git diff --check`: 成功。

## 対象外

- tkinterの「翻訳テスト」相当のUI。パイプライン経由の実翻訳で代替する方針のため実装しない。
- tkinterの撤去（段階8）。
- ドキュメントの全面更新（段階9）。
- Python側の変更。段階4のAPI契約だけで実装できたため変更していない。
