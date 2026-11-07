# Issue #182 複雑背景のOCR品質改善

- Base/Merge target: `develop`、ブランチ `task/182-ocr-complex-background`。親 #76。`app.py`・pipeline・observabilityは未変更(#173との競合回避)。Web版共有の`src/app/ocr.py`も未変更。

## やったこと
- `engines/ocr_preprocess.py`(拡大・メディアン・大津二値化・白縁、純粋関数)、`ocr_select.py`(平均信頼度・候補選択・低信頼度除外・矩形クランプ)、`robust_ocr.py`(`TesseractOcrEngine`派生、二値化→グレースケールの順に試す)。`factory.py`でserverのOCRに採用。
- 単体試験 `server/tests/test_ocr_quality.py`(16件)。結合試験 `test_pipeline.py`に複雑群15%の判定、回帰検出用2%上限、領域信頼度下限、配信矩形の座標位置を追加(基準の緩和はしていない)。

## 測定(固定画像13枚、実Tesseract)
- 改善前: 明瞭0.0%、複雑56.2%。改善後: 明瞭0.0%、複雑0.0%。方式別の表は docs/v1.0/testing.md。
- 追加の難例(自作・非固定): 明暗分割背景約70%、高コントラスト市松90〜100%は未達。理由と代替案はtesting.mdの「Ownerへ提示すべき事項」。

## mutation(integration test_pipeline.py)
| 変異 | 結果 |
| --- | --- |
| 二値化候補を外す(グレースケールのみ) | 検出(複雑9.2% > 回帰上限2%) |
| 倍率3→2 | 検出(同上) |
| 領域信頼度下限0.60→0 | 検出(unreadable群が空にならない) |
| 座標から白縁を引かない | 検出(配信矩形位置) |
| メディアン5→1 | 結合では未検出(固定画像に不要)。単体のスペックル試験で検出 |

## 注意
- 小標本。最終判定は#109の200枚正解集合。
