#!/usr/bin/env bash
# Start the HV Closure Engine prototype on http://localhost:8000
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3.14 -m venv .venv || python3.13 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8000}" "$@"
