FROM node:24-slim AS frontend-deps

WORKDIR /frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci


FROM frontend-deps AS frontend-build

COPY frontend/ ./
RUN npm run build


FROM frontend-build AS frontend-test

RUN npm run lint
RUN npx vitest run


FROM python:3.14-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Argos Translateが依存するPyTorchは、用途に不要なCUDAランタイムを含めない。
RUN pip install --no-cache-dir torch==2.13.0+cpu --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY --from=frontend-build /frontend/dist ./frontend/dist

ENV PYTHONPATH=/app/src

CMD ["python", "-m", "unittest", "discover", "-s", "src/tests"]
