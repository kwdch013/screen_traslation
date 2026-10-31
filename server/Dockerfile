# 本番(runtime)とテスト(test)で依存の層を共有する。既定(最終ステージ)はtestのまま保ち、
# 既存のcompose.test.ymlとCIの挙動を変えない。本番は target: runtime で選ぶ。
FROM python:3.14-slim AS base

WORKDIR /workspace

RUN apt-get update \
	&& apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
	&& rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./app-requirements.txt
COPY server/requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir torch==2.13.0+cpu --index-url https://download.pytorch.org/whl/cpu \
	&& python -m pip install --no-cache-dir -r app-requirements.txt -r requirements.txt

COPY src/ ./src/
COPY server/src/ ./server/src/

ENV PYTHONPATH=/workspace/server/src:/workspace/src


# 本番: 非root・書き込み先は名前付きvolumeだけ。秘密(TLS鍵・トークン)はイメージへ入れない。
FROM base AS runtime

# UID/GIDはComposeのuser指定と揃える。volumeの初回作成時にこの所有者が引き継がれる。
RUN groupadd --system --gid 10001 translation \
	&& useradd --system --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin translation \
	&& mkdir -p /data /credentials /models \
	&& chown 10001:10001 /data /credentials /models

COPY server/deploy/model-manifest.json /opt/screen-translation/model-manifest.json

ENV PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1 \
	SCREEN_TRANSLATION_MODEL_MANIFEST=/opt/screen-translation/model-manifest.json

USER 10001:10001
EXPOSE 8443
CMD ["python", "-m", "screen_translation_server"]


# テスト(既定の最終ステージ)。
FROM base AS test

COPY server/requirements-dev.txt ./requirements-dev.txt
RUN python -m pip install --no-cache-dir -r requirements-dev.txt
COPY server/tests/ ./tests/
COPY contracts/ ./contracts/
# 本番構成の静的検証(tests/test_production_*.py)が読む。リポジトリ上のserver/と同じ相対配置にする。
COPY server/Dockerfile server/compose.yml server/.env.example ./
COPY server/deploy/ ./deploy/

CMD ["python", "-B", "-m", "unittest", "discover", "-s", "tests", "-v"]
