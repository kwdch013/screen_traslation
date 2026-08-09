# 実行コマンド

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m unittest discover -s src/tests
.\.venv\Scripts\python.exe -m compileall -q src/app
.\.venv\Scripts\python.exe -m app.evaluate_test_images --engine tesseract
.\.venv\Scripts\python.exe -m app.evaluate_translations --engine argos
```

Ollama VLM計測時:

```powershell
$env:PYTHONPATH = "src"
winget install --id Ollama.Ollama --source winget --accept-package-agreements --accept-source-agreements
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" pull gemma3:4b
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" pull minicpm-v
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" pull qwen2.5vl:7b
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" pull gemma3:12b
.\.venv\Scripts\python.exe -m app.evaluate_test_images --engine llm --llm-base-url http://127.0.0.1:11434/v1 --llm-model gemma3:4b --llm-timeout 300
.\.venv\Scripts\python.exe -m app.evaluate_test_images --engine llm --llm-base-url http://127.0.0.1:11434/v1 --llm-model minicpm-v --llm-timeout 300
.\.venv\Scripts\python.exe -m app.evaluate_test_images --engine llm --llm-base-url http://127.0.0.1:11434/v1 --llm-model qwen2.5vl:7b --llm-timeout 300
.\.venv\Scripts\python.exe -m app.evaluate_test_images --engine llm --llm-base-url http://127.0.0.1:11434/v1 --llm-model gemma3:12b --llm-timeout 300
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" ps
C:\Windows\System32\nvidia-smi.exe --query-gpu=memory.total,memory.used,memory.free,utilization.gpu --format=csv,noheader,nounits
```

不要モデル削除:

```powershell
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" rm gemma3:4b
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" rm gemma3:12b
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" rm minicpm-v
```
