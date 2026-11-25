# Start the HV Closure Engine on http://localhost:8000 (Windows / PowerShell)
# Needs Python 3.13 or 3.14 (onnxruntime has no 3.15 wheels yet) and Google Chrome.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path .venv)) {
    py -3.14 -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -q --upgrade pip
    .\.venv\Scripts\python.exe -m pip install -q -r requirements.txt
}
$port = if ($env:PORT) { $env:PORT } else { "8000" }
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port $port @args
