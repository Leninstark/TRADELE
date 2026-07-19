#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if [[ -z "$VIRTUAL_ENV" ]]; then
  if [[ -d .venv ]]; then
    source .venv/bin/activate
  else
    echo "Create venv first: python3.11 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    exit 1
  fi
fi
# Package was renamed from app to TRADELE — do not use app.main:app
uvicorn TRADELE.main:app --reload --host 0.0.0.0 --port 8000
