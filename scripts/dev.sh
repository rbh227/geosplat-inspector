#!/usr/bin/env bash
# One-command dev environment: FastAPI backend (:8000) + Vite dev server (:5173).
# Ctrl-C stops both.
#
# Model config: a choice saved in the in-app Settings (gear icon) always wins;
# otherwise the local-model env below applies (server side of that path:
# scripts/local-model.sh up).
set -euo pipefail
cd "$(dirname "$0")/.."

: "${MODEL_PROVIDER:=openai}"
: "${MODEL_NAME:=Qwen/Qwen3-VL-8B-Instruct-FP8}"
: "${OPENAI_BASE_URL:=http://localhost:8001/v1}"
: "${OPENAI_API_KEY:=not-needed}"
export MODEL_PROVIDER MODEL_NAME OPENAI_BASE_URL OPENAI_API_KEY

.venv-api/bin/python -m uvicorn backend.server:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!
trap 'kill "$BACKEND_PID" 2>/dev/null' EXIT

npm run dev
