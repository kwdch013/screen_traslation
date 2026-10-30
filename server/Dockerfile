FROM python:3.14-slim

WORKDIR /workspace
ENV PYTHONPATH=/workspace/src
COPY requirements.txt requirements-dev.txt ./
RUN python -m pip install --no-cache-dir -r requirements-dev.txt
COPY src/ ./src/
COPY tests/ ./tests/

CMD ["python", "-B", "-m", "unittest", "discover", "-s", "tests", "-v"]
