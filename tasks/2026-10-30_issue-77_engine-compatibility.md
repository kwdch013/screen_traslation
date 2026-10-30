# Issue #77 OCR・翻訳コア共有

## 目的

旧Web版のOCR・翻訳コアをserverから再利用し、共有fixtureと実エンジンで互換性を確かめる。

## 実装

- `app.factory.build_shared_translation_engines()` を追加し、既存のTesseract英語OCR・Argos英日翻訳を独立Glossary付きで構成する。
- serverに薄いengine公開境界を追加し、OCR・翻訳アルゴリズムを複製せず既存 `src/app` を参照する。
- serverテスト用Python 3.14イメージへCPU版Torch、Tesseract、Argos英日モデルを導入し、互換fixture試験と実エンジン試験を実行する。
- ロードマップと開発ガイドに、#77の確認範囲と後続の製品ready/性能/品質検証を記録する。

## 検証

- TDD: `server/tests/test_engine_compatibility.py` とfixtureを実装前に追加し、adapter追加前にテストを実行。
- `docker compose -f server/compose.test.yml run --build --rm test`: 14件成功。Tesseract/Argos実エンジン試験を含む。
- `docker build -t app:ci . && docker run --rm -e PYTHONPATH=/app/src app:ci python -B -m unittest discover -s src/tests`: 306件成功、72件skip。
- マウント付き同テスト: 306件成功。
- `mypy src` / `mypy --platform win32 src`: 各79 source files成功。server engine境界の追加mypy: 3 source files成功。
- Ruff (src/scripts/tests/ai_gate/server): 全チェック成功。
- frontend CI相当: ホスト構成・文書・撤去試験16件成功、frontend lint/Vitest build成功。

## 制約・後続

Web経路、任意LLM評価、既存Webの設定・保存先・ログ動作は変更しない。モデルready時間、資源上限、製品品質と性能は#81/#109で評価する。
