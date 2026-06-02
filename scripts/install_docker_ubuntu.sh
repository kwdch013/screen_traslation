#!/usr/bin/env bash
set -euo pipefail

sudo apt update
sudo apt install -y docker.io docker-compose-v2
sudo usermod -aG docker "$USER"

echo "Dockerを利用するには、WSL/シェルを再起動してください。"
