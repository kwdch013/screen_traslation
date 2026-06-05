# 実行コマンド

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m unittest discover -s src/tests
.\.venv\Scripts\python.exe -m compileall -q src/app
.\.venv\Scripts\python.exe -m app.evaluate_test_images --engine tesseract
.\.venv\Scripts\python.exe -m app.evaluate_translations --engine argos
.\.venv\Scripts\python.exe -m app.evaluate_translations --engine ctranslate2 --model-path models/opus-mt-en-jap-ct2
```

Ollama VLM計測時:

```powershell
$env:PYTHONPATH = "src"
winget install --id Ollama.Ollama --source winget --accept-package-agreements --accept-source-agreements
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" pull gemma3:4b
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" pull minicpm-v
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" pull gemma3:12b
.\.venv\Scripts\python.exe -m app.evaluate_test_images --engine llm --llm-base-url http://127.0.0.1:11434/v1 --llm-model gemma3:4b --llm-timeout 300
.\.venv\Scripts\python.exe -m app.evaluate_test_images --engine llm --llm-base-url http://127.0.0.1:11434/v1 --llm-model minicpm-v --llm-timeout 300
.\.venv\Scripts\python.exe -m app.evaluate_test_images --engine llm --llm-base-url http://127.0.0.1:11434/v1 --llm-model gemma3:12b --llm-timeout 300
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" ps
C:\Windows\System32\nvidia-smi.exe --query-gpu=memory.total,memory.used,memory.free,utilization.gpu --format=csv,noheader,nounits
```
