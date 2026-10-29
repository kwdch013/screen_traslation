FROM python:3.14-slim
WORKDIR /workspace
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY scripts ./scripts
COPY .githooks ./.githooks
COPY .github/workflows ./.github/workflows
COPY tests/ai_gate ./tests/ai_gate
CMD ["python", "-B", "-m", "unittest", "discover", "-s", "tests/ai_gate", "-v"]
