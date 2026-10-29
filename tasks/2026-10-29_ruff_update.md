# Ruff 0.16.1更新の互換性修正

## 対象

- Issue #112 / PR #39。
- 旧Web版の依存更新。Ownerが既存16件について了承した例外により、現行dev・既存PRで対応する。AI Review Gate導入と作成時Work Unit記録は今回の対象外とし、独立レビューと必須CIを維持する。

## 原因と変更

- Ruff 0.16.0で既定ルールが59件から413件へ拡張され、元のPRは79件の指摘で失敗した。
- `ruff.toml` に従来の `E4`・`E7`・`E9`・`F` を明示した。ルールの追加導入はこの依存更新から分ける。
- Dockerfileに設定を含め、コンテナ内とホスト側の検査範囲を合わせた。
- 回帰テストは既存のimport順を許容することと、未定義変数を引き続き拒否することを検証する。

## 検証

- 修正前: 元HEADのlintは79件の指摘。設定未配置の実行イメージで追加テスト2件の失敗を確認。
- 修正後: 実行イメージの単体・実サーバーテスト247件成功（実行イメージに含めない構成・文書21件は別実行で成功）、Ruff成功、mypy Linux/Windows各73ファイル成功。
- フロントエンド: コンテナでbuild・lint・vitest 81件成功。
- 最終HEADのGitHub CIと独立レビュー結果はPR本文・レビューコメントに記録する。

## 参照

- https://github.com/astral-sh/ruff/releases/tag/0.16.0
- https://github.com/kwdch013/screen_traslation/issues/112
