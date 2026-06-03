#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
source .venv/bin/activate
uvicorn agent.main:app --reload --port "${API_PORT:-8000}"
