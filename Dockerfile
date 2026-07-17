FROM python:3.14-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        tk \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Argos Translateが依存するPyTorchは、用途に不要なCUDAランタイムを含めない。
RUN pip install --no-cache-dir torch==2.13.0+cpu --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src

ENV PYTHONPATH=/app/src

CMD ["python", "-m", "unittest", "discover", "-s", "src/tests"]
