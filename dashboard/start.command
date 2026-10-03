#!/bin/zsh
set -e
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import yfinance' >/dev/null 2>&1; then
  .venv/bin/python -m pip install -r requirements.txt
fi
if .venv/bin/python - <<'PY'
import json, sys, urllib.request
try:
    with urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=2) as response:
        healthy = json.load(response).get('service') == 'FinFeed'
except Exception:
    healthy = False
sys.exit(0 if healthy else 1)
PY
then
  open 'http://127.0.0.1:8765'
  exit 0
fi
exec .venv/bin/python server.py --open
