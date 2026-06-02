# 2026-06-02 Docker整備

## 作業内容

- `Dockerfile` にTesseract OCR本体と英語データのインストールを追加した。
- `docker-compose.yml` の既定コマンドをテスト実行に変更した。
- Ubuntu向けDockerインストール補助スクリプトを追加した。

## Dockerインストールについて

この実行環境では `sudo` が対話認証を要求し、Codexからパスワード入力用TTYを提供できないため、Docker本体のインストールは実施できなかった。

実行した確認:

- `docker --version`: 未導入
- `sudo apt update`: `sudo: A terminal is required to authenticate`
- `sudo -n true`: `sudo: interactive authentication is required`

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
