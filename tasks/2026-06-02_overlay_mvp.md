# 2026-06-02 オーバーレイMVP実装

## 作業内容

- オーバーレイ方式を前提に、画面取得、OCR、翻訳、辞書、表示、パイプラインを疎結合なモジュールとして追加する。
- OCRの実行頻度を下げられる `FrameLimiter` を追加する。
- 用語登録用の `Glossary` を追加し、JSONで保存、読み込みできるようにする。
- 翻訳結果のキャッシュを追加し、同じ文字列を繰り返し翻訳しないようにする。
- 初期検証用に、任意テキストをOCR結果として扱うCLIを追加する。
- 初期UI方針に合わせて、辞書登録と翻訳テストができるデスクトップアプリの入口を追加する。
- Python 3.14ベースのコンテナ定義を追加する。

## 反映した決定事項

- 初期対象言語は英語のみ。
- 翻訳対象は可能ならUI全体。
- 翻訳はローカル処理優先。
- 外部翻訳APIは完全無料の場合のみ任意で許可。
- UIはデスクトップアプリ。
- 優先指標はGPU速度、遅延、翻訳精度、実装速度。

## テスト

- 辞書登録、保存、読み込み
- 辞書の完全一致翻訳と部分置換
- OCR FPS制御
- 翻訳キャッシュ
- 信頼度の低いOCR結果の除外
- 設定ファイルの保存、読み込み

## 実行結果

- `PYTHONPATH=src python3 -m unittest discover -s src/tests`
- `PYTHONPATH=src python3 -m app.main --config /tmp/screen_translation_app.json --glossary /tmp/screen_translation_glossary.json --text "New Game"`
- `PYTHONPATH=src python3 -m py_compile src/app/*.py`
- `PYTHONPATH=src python3 -c "from app.desktop_app import DesktopApplication; print(DesktopApplication.__name__)"`

## 追加実装

- `mss` による画面キャプチャアダプタを追加した。
- `pytesseract` によるOCRアダプタを追加した。
- Argos Translateによるローカル翻訳アダプタを追加した。
- Argos Translate英日モデル導入コマンドを追加した。
- Tkによる透過オーバーレイを追加した。
- 起動中ウィンドウ選択を追加した。
- デスクトップアプリから翻訳開始、停止できるようにした。
- 仕様書、利用手順書、開発者向け説明書を追加した。

## 未実行

- `docker compose build`
- 理由: 現在の実行環境に `docker` コマンドが存在しないため。
