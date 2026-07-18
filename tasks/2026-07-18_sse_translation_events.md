# 2026-07-18 翻訳結果のSSE配信

## 背景

- Issue #8「ウェブアプリ化(3/9)」として、Tkオーバーレイだけが受け取っていた翻訳結果をブラウザへリアルタイム配信する。
- 後続のプレビュー重畳に必要なフレーム寸法、セッション世代、フレームID、座標利用可否を含む結果イベント契約を先に確定する。
- 段階2で分離したセッション世代とRunner世代を維持し、SSEの結果照合にはセッション世代だけを使う。

## 実装

- `TranslationResult`と`ResultPublisher`を追加し、世代、フレームID、取得・処理時刻、フレーム寸法、翻訳領域をJSON化できる契約にした。
- `TextRegion` / `TranslationRegion`へ`positioning`を後方互換な既定値付きで追加した。Tesseractは`available`、LLM OCRは`unavailable`を返し、パイプラインで結果イベントまで引き継ぐ。
- `WebCaptureFrameStore`へ、セッション消去後も巻き戻らない単調増加フレームIDを追加した。パイプラインは処理済みIDと同じフレームを再度OCRしない。
- Tesseractへ渡す画像が前処理で2倍になった場合、OCR座標を1/2へ戻してから行・ブロックを組み立てるようにした。
- `TranslationEventPublisher`を追加した。購読者ごとに有界キューを持ち、満杯時は最古のイベントを捨てて最新結果を入れる。複数購読者へ同じ結果を配信する。
- Publisherを`WebAppService`の寿命で保持し、開始、停止、再選択、異常終了を`state`イベントとして通知する。世代変更時は各キュー内の旧結果を消去し、遅れて到着した旧世代結果も拒否する。
- OCR中に世代が変わった場合は結果を発行済み扱いにせず、現行世代で同じフレームを再処理できるようにした。
- `GET /api/events`を追加し、`translation_result` / `state`イベントと15秒間隔のheartbeatコメントを配信する。共通Host検証とローカルOrigin検証を適用する。
- Web向けパイプライン組み立てを`web_pipeline.py`へ分け、`web_app_service.py`を300行未満に維持した。
- `docs/specification.md`へSSEフィールド、座標系、`positioning`、キュー、世代破棄の契約を追記した。

## テスト

### Red

- `TranslationResult` / SSE Publisher / SSE APIが未定義でImportErrorになることを確認した。
- Tesseract座標変換引数、`positioning`、フレームIDが存在せず、対応する回帰テストが失敗することを確認した。
- 世代変更中にOCRしたフレームを処理済みにすると、新世代で再処理されない回帰テストの失敗を確認した。
- 同じRed実行に含めた既存の実サーバーテストは、ローカルサンドボックスのソケット生成禁止により`PermissionError`となった。

### Green

- 結果JSON契約、Tesseract元画像座標、LLM OCRの位置情報なし、フレームID継続、同一フレーム二重OCR防止、空結果を確認するテストを追加した。
- 複数購読、キュー溢れ時の最古破棄、再選択・停止後の旧世代破棄、SSE整形、heartbeat、Origin拒否を確認するテストを追加した。
- OCR中の世代変更では旧結果を出さず、新世代でもう一度処理するテストを追加した。
- ソケット不要の追加・関連テスト49件は成功した。

### 最終確認

- `docker compose build app`: 成功。
- `docker compose run --rm app python -m unittest discover -s src/tests`: 171件実行、失敗0件、既存の環境依存テスト2件skip。
- 一時コンテナへ開発用固定版`ruff==0.15.22`を導入して`ruff check src`: 成功(`All checks passed!`)。
- `PYTHONPATH=src .venv/bin/python -m py_compile src/app/*.py src/tests/*.py`: 成功。
- `git diff --check`: 成功。
- ローカルvenvの全実サーバーテストはソケット生成禁止のため実行できないが、同じテストをソケット利用可能なDockerコンテナ内で含めて171件実行し、失敗0件を確認した。

## 対象外

- ReactフロントエンドでのSSE購読、プレビュー重畳、字幕リスト表示。
- 設定・辞書API。
- tkinterの撤去、既存`OverlayRenderer`実装の置き換え。
- SSEの別オリジン公開、トークン認証、リバースプロキシ越しの公開。
