# v1.0 第三者コンポーネントとモデルのライセンス棚卸し

この文書は、v1.0（Windowsクライアント + Linuxサーバー）が利用する第三者のソフトウェアと翻訳モデルについて、出典・版・提供元が示すライセンス・再配布条件・同梱判断を一覧にしたものです（REQ-F-012、REQ-NF-009）。

## 位置づけ（必ず読むこと）

- **ライセンスの最終確認と採用可否の判断はOwnerが行います。** この一覧の「提供元の表示」列は、各提供元が公開している表示を調査時点で転記したものです。全文の読み合わせ、条件の解釈、再配布の可否の確定は**未実施で、確認済みではありません**。全行の状態は「未確認（Owner判断待ち）」です。
- **本製品自体のライセンスは未決定です**（Owner判断待ち）。リポジトリにもLICENSEファイルを置いていません。この文書は本製品のライセンスを宣言しません。
- 推移依存（上記が引き込む他のパッケージ）は、版が導入のたびに解決されるため個別に棚卸ししていません。Owner判断の前に、次のコマンドで実際に入る一覧を取得して追加棚卸しが必要です（未実施）。

  ```sh
  docker compose -f server/compose.yml run --rm --no-deps server python -m pip list --format=freeze
  ```

- 版は、このリポジトリの定義（`server/requirements.txt`、`requirements.txt`、`server/deploy/model-manifest.json`、`server/deploy/stanza-manifest.json`、`client/src/ScreenTranslation.Windows/ScreenTranslation.Windows.csproj`、`client/global.json`）が固定または許容する値です。範囲指定（`>=`）の行は導入時に解決された版が入るため、実際の版は上記コマンドで確認します。

## 同梱するか、利用者が取得するかの判断

| 配布物 | 判断 | 理由 |
|---|---|---|
| Windows配布物（zip） | .NETランタイム・WPF・`System.Security.Cryptography.ProtectedData` を**同梱する** | 自己完結配布（REQ-F-012）のため。利用者にSDKを要求しない。ライセンス通知は配布物内の `THIRD-PARTY-NOTICES.txt`（原本は `client/publish/THIRD-PARTY-NOTICES.txt`）に同梱する |
| Linuxサーバーのコンテナイメージ | Python・Pythonパッケージ・Tesseract本体と英語学習データを**運用者がビルドして入れる**。リポジトリはイメージを配布しない | `server/Dockerfile` が公式パッケージ配布元から導入する。本リポジトリがこれらを再配布するわけではない |
| 翻訳モデル（Argos英日）・Stanza文分割資源 | イメージ・リポジトリへ**同梱しない**。運用者が準備段階（`prepare-model`）で取得元から取得し、サイズ・SHA-256を検証して導入する | 再配布条件が未確認のため。取得元の条件は取得した運用者とOwnerが確認する（`license_accepted` はOwnerの確認証跡） |
| Windowsクライアントに翻訳モデル | 含めない | モデルはLinuxサーバー側にのみある |

同梱方針を変える（モデルの同梱、イメージの公開など）ときは、先にOwnerがこの一覧の該当行のライセンスと再配布条件を確認し、判断をIssueまたはPRに記録してから行います。

## 棚卸し一覧

列は、項目・出典・版・提供元の表示するライセンス・同梱方針・再配布条件と備考・確認状態です。

| 項目 | 出典 | 版 | 提供元の表示するライセンス | 同梱方針 | 再配布条件・備考 | 確認状態 |
|---|---|---|---|---|---|---|
| .NET ランタイム | https://github.com/dotnet/runtime | SDK 10.0.402 系（`client/global.json`）。自己完結配布のランタイム | MIT | 同梱する（Windows配布物） | 著作権表示とライセンス文の保持。ランタイムが含む第三者の表示は https://github.com/dotnet/runtime/blob/main/THIRD-PARTY-NOTICES.TXT を参照 | 未確認（Owner判断待ち） |
| WPF | https://github.com/dotnet/wpf | .NETランタイムと同じ | MIT | 同梱する（Windows配布物） | 同上 | 未確認（Owner判断待ち） |
| System.Security.Cryptography.ProtectedData | https://www.nuget.org/packages/System.Security.Cryptography.ProtectedData/10.0.0 | 10.0.0 | MIT | 同梱する（Windows配布物） | 資格情報のDPAPI保護に使用。通知は配布物の `THIRD-PARTY-NOTICES.txt` | 未確認（Owner判断待ち） |
| Python | https://www.python.org/ | 3.14（コンテナの基盤イメージ `python:3.14-slim`） | PSF License | 同梱しない（運用者が基盤イメージを取得） | 基盤イメージはDebian系で、他のOSパッケージのライセンスも含む。基盤イメージの全パッケージは未棚卸し | 未確認（Owner判断待ち） |
| tesseract-ocr | Debianパッケージ（`server/Dockerfile` が `apt-get` で導入）。上流 https://github.com/tesseract-ocr/tesseract | OSパッケージの版（基盤イメージ内で `tesseract --version` で確認する） | Apache-2.0（上流の表示） | 同梱しない（イメージのビルド時に運用者が取得） | 英日翻訳の前段のOCRに使用。イメージ再ビルドで更新する | 未確認（Owner判断待ち） |
| tesseract-ocr-eng | Debianパッケージ。上流 https://github.com/tesseract-ocr/tessdata | OSパッケージの版（`dpkg -s tesseract-ocr-eng` で確認する） | Apache-2.0（上流の表示） | 同梱しない（イメージのビルド時に運用者が取得） | 英語の学習データ | 未確認（Owner判断待ち） |
| Argos Translate（argostranslate） | https://github.com/argosopentech/argos-translate | `>=1.11.0`（`requirements.txt`） | MIT（上流の表示） | 同梱しない（イメージのビルド時にpipで取得） | 翻訳エンジン本体。モデルとは別のライセンス | 未確認（Owner判断待ち） |
| Argos英日モデル | https://argos-net.com/v1/translate-en_ja-1_1.argosmodel | 1.1（サイズ120470284 byte、SHA-256は `server/deploy/model-manifest.json`） | 提供元の明示が確認できていない。manifestは「利用・再配布条件は導入前に運用者が確認する」と記録 | 同梱しない（`prepare-model` が取得して検証） | 再配布条件が未確認のため、イメージ・リポジトリへ入れない。`license_accepted` は、Ownerが条件を確認した証跡としてのみ真にする | 未確認（Owner判断待ち）。manifestの `license_accepted` は運用上の導入ゲートで、Ownerの最終確認の代わりではない |
| Stanza（stanza） | https://github.com/stanfordnlp/stanza | argostranslateの依存として解決される版（未棚卸し） | Apache-2.0（上流の表示） | 同梱しない（pipで取得） | 文分割に使用。実行時はモデルを取得しない製品側の固定がある | 未確認（Owner判断待ち） |
| Stanza資源 resources.json | https://github.com/stanfordnlp/stanza-resources | 1.10.0（コミット固定、`server/deploy/stanza-manifest.json`） | 取得元リポジトリの表示を要確認 | 同梱しない（`prepare-model` が取得して検証） | 取得元の更新はSHA-256不一致で準備失敗になる（意図した動作） | 未確認（Owner判断待ち） |
| Stanza英語モデル | https://huggingface.co/stanfordnlp/stanza-en | 1.10.0（tokenize・mwtの3ファイル、コミット固定） | 取得元のモデルカードの表示を要確認 | 同梱しない（`prepare-model` が取得して検証） | 英語以外の言語は対象外（REQ-F-004） | 未確認（Owner判断待ち） |
| torch | https://pytorch.org/ | 2.13.0+cpu（`server/Dockerfile`） | BSD-3-Clause系（上流の表示） | 同梱しない（イメージのビルド時に取得） | CPU版を専用のindexから導入。GPUは使わない | 未確認（Owner判断待ち） |
| Pillow（pillow） | https://python-pillow.org/ | `>=12.3.0` | MIT-CMU（HPND系、上流の表示） | 同梱しない（pipで取得） | 画像の検証・変換 | 未確認（Owner判断待ち） |
| pytesseract | https://github.com/madmaze/pytesseract | `>=0.3.13` | Apache-2.0（上流の表示） | 同梱しない（pipで取得） | tesseractの呼び出し | 未確認（Owner判断待ち） |
| FastAPI（fastapi） | https://github.com/fastapi/fastapi | `>=0.141.1` | MIT（上流の表示） | 同梱しない（pipで取得） | 既存Web版が使用。v1.0サーバーはStarletteを直接使用 | 未確認（Owner判断待ち） |
| httpx2 | https://pypi.org/project/httpx2/ | `>=2.7.0` | 提供元の表示を要確認 | 同梱しない（pipで取得） | 既存Web版の依存（`requirements.txt`）。提供元と版の経緯は未調査 | 未確認（Owner判断待ち） |
| Starlette（starlette） | https://github.com/encode/starlette | 1.10.0（`server/requirements.txt`） | BSD-3-Clause（上流の表示） | 同梱しない（pipで取得） | v1.0サーバーのASGI入口（ADR-0001） | 未確認（Owner判断待ち） |
| Uvicorn（uvicorn） | https://github.com/encode/uvicorn | 0.52.4（`server/requirements.txt`）。ルートは `>=0.52.1,<0.53.0` | BSD-3-Clause（上流の表示） | 同梱しない（pipで取得） | TLS終端を含むサーバー | 未確認（Owner判断待ち） |
| websockets | https://github.com/python-websockets/websockets | 15.0.1（`server/requirements.txt`） | BSD-3-Clause（上流の表示） | 同梱しない（pipで取得） | WSS | 未確認（Owner判断待ち） |
| jsonschema | https://github.com/python-jsonschema/jsonschema | 4.26.0（`server/requirements.txt`） | MIT（上流の表示） | 同梱しない（pipで取得） | 契約スキーマの検証 | 未確認（Owner判断待ち） |

## Owner判断待ちの項目

1. 本製品自体のライセンス（未決定）。
2. 上の各行の全文確認と採用可否。特に次は提供元の表示が確認できていない、または取得元ごとに条件が異なります。
   - Argos英日モデルの利用・再配布条件。
   - Stanza資源（resources.json、英語モデル）の取得元の表示。
   - httpx2の提供元と表示。
3. 推移依存の追加棚卸し（上記のコマンドで取得し、一覧へ追記する）。
4. 同梱方針の変更（モデルの同梱、コンテナイメージやWindows配布物の公開）をする場合の再配布条件の確認。
5. Windows配布物のコード署名の要否（[install-client.md](install-client.md#署名について)）。

判断はIssueまたはPRのコメントに記録し、この文書の「確認状態」を更新してください。エージェントや運用者は、Ownerの記録がない行を確認済みとみなしません。

## 更新の手順

- 依存を追加・更新したら、この一覧と `client/publish/THIRD-PARTY-NOTICES.txt` を更新します。`src/tests/test_v1_install_docs.py` が、依存定義・manifest・csprojとの差を検出します。
- モデル・Stanza資源の取得元を更新するときは、[manifest更新手順](operations.md#モデルstanza資源のmanifest更新手順)の「ライセンスの確認観点」に従い、Ownerへ判断を依頼します。

## 要件との対応

| 要件 | この文書での扱い |
|---|---|
| REQ-F-012 | 配布物・モデルの同梱判断と、導入条件を追跡できる一覧 |
| REQ-NF-009 | 特定の実機情報・秘密を含まない。ライセンス確認はOwner判断として残す |
