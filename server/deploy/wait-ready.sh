#!/bin/sh
# サーバーが /api/v1/ready=200 になるまで待つ。トークンは引数・環境変数に置かず、ファイルから標準入力で渡す。
# 使い方: server/deploy/wait-ready.sh <端末または管理トークンのファイル> [待機秒数(既定 300)]
# 導入済みモデルのready目標は120秒、空のモデル領域からの準備は最大1800秒。
set -eu

token_file="${1:?トークンファイルを指定してください}"
limit="${2:-300}"
compose_file="$(dirname "$0")/../compose.yml"
[ -r "$token_file" ] || { echo "トークンファイルを読めません" >&2; exit 2; }

deadline=$(( $(date +%s) + limit ))
while :; do
	if docker compose -f "$compose_file" exec -T server \
		python -m screen_translation_server.healthcheck --ready --token-file - < "$token_file" 2>/dev/null; then
		echo "ready"
		exit 0
	fi
	if [ "$(date +%s)" -ge "$deadline" ]; then
		echo "ready になりませんでした (${limit}秒)。docker compose logs server を確認してください" >&2
		exit 1
	fi
	sleep 5
done
