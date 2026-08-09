# 2026-06-02 Docker整備

## 作業内容

- `Dockerfile` にTesseract OCR本体と英語データのインストールを追加した。
- `docker-compose.yml` の既定コマンドをテスト実行に変更した。
- Ubuntu向けDockerインストール補助スクリプトを追加した。

## Dockerインストールについて

この実行環境では `sudo` が対話認証を要求し、Codexからパスワード入力用TTYを提供できないため、Docker本体のインストールは実施できなかった。

最終確認時点ではDocker CLIとComposeが利用可能になっていたが、Dockerデーモンのソケット権限によりビルドは実行できなかった。

実行した確認:

- `docker --version`: 未導入
- `sudo apt update`: `sudo: A terminal is required to authenticate`
- `sudo -n true`: `sudo: interactive authentication is required`
- `docker --version`: `Docker version 29.1.3, build 29.1.3-0ubuntu4.1`
- `docker compose version`: `Docker Compose version 2.40.3+ds1-0ubuntu1`
- `docker compose build`: Dockerソケットのpermission denied
- `docker compose build`: 2026-06-02 22:08 に通常実行と権限昇格付き実行で再確認。どちらもDockerソケットのpermission denied
- `docker info`: クライアント情報は表示されるが、サーバー接続でpermission denied
- `PYTHONPATH=src python3 -m unittest discover -s src/tests`: 成功。15件のテストが通過
- `docker info`: 2026-06-02 22:18 に権限付き実行でDockerサーバー接続に成功
- `docker compose build`: 2026-06-02 22:26 に成功
- `docker compose run --rm app`: 2026-06-02 22:26 に成功。15件のテストが通過

## 手動インストール手順

```bash
scripts/install_docker_ubuntu.sh
```

または次を実行する。

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-v2
sudo usermod -aG docker "$USER"
```

実行後、WSLまたはシェルを再起動する。
