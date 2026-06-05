# 実行コマンド

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m unittest discover -s src/tests
.\.venv\Scripts\python.exe -m compileall -q src/app
.\.venv\Scripts\python.exe -m app.evaluate_test_images --engine tesseract
.\.venv\Scripts\python.exe -m app.evaluate_translations --engine argos
.\.venv\Scripts\python.exe -m app.evaluate_translations --engine ctranslate2 --model-path models/opus-mt-en-jap-ct2
```

LLM/VLM計測時:

```powershell
$env:PYTHONPATH = "src"
$env:LLM_BASE_URL = "http://127.0.0.1:8000/v1"
$env:LLM_MODEL = "your-model"
.\.venv\Scripts\python.exe -m app.evaluate_test_images --engine llm
.\.venv\Scripts\python.exe -m app.evaluate_translations --engine llm
```
