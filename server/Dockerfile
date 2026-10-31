FROM python:3.14-slim

WORKDIR /workspace
ENV PYTHONPATH=/workspace/src

RUN apt-get update \
	&& apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
	&& rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./app-requirements.txt
COPY server/requirements.txt server/requirements-dev.txt ./
RUN python -m pip install --no-cache-dir torch==2.13.0+cpu --index-url https://download.pytorch.org/whl/cpu \
	&& python -m pip install --no-cache-dir -r app-requirements.txt -r requirements-dev.txt

COPY src/ ./src/
COPY server/src/ ./server/src/
COPY server/tests/ ./tests/
COPY contracts/ ./contracts/

ENV PYTHONPATH=/workspace/server/src:/workspace/src

CMD ["python", "-B", "-m", "unittest", "discover", "-s", "tests", "-v"]
