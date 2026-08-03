#!/usr/bin/env bash
# One command to bring up EVERYTHING SplatAgent needs:
#
#   1. the vLLM model endpoint (remote GPU box + SSH tunnel on :8001)
#   2. the FastAPI backend (:8000)
#   3. the Vite dev server (:5173)
#
# Ctrl-C stops whatever this script started (anything already running is left
# alone, so re-running is safe).
#
# Why the model check exists: the backend and Vite come up fine without a model
# server, so the app LOOKS healthy right up until the first agent run fails with
# "provider error: Connection error." That error almost always means the SSH
# tunnel on :8001 is down — typically a VPN blip, while the vLLM server itself
# is still up on the GPU box for days. This script checks the model path FIRST
# and says so plainly rather than letting you find out from the chat panel.
#
# Flags:
#   --no-model    skip the model bring-up entirely (viewer/editor work fine)
#   --model-only  bring up the model endpoint, then exit
set -uo pipefail
cd "$(dirname "$0")/.."

MODEL_PORT="${VLLM_LOCAL_PORT:-8001}"
BACKEND_PORT=8000
VITE_PORT=5173

# ONE model identity end to end (Codex review P1): scripts/local-model.env's
# VLLM_MODEL drives BOTH the vLLM server (local-model.sh sources the same
# file) and the backend's MODEL_NAME, so the backend can never request a
# model the endpoint doesn't serve. The fallback literal matches
# local-model.sh's own default. Explicit MODEL_NAME env still wins.
# A model chosen in the in-app Settings (gear) is stored in
# backend/.data/settings.json and ALWAYS wins over all of these.
[ -f scripts/local-model.env ] && . scripts/local-model.env
: "${MODEL_PROVIDER:=openai}"
: "${MODEL_NAME:=${VLLM_MODEL:-Qwen/Qwen3-VL-8B-Instruct-FP8}}"

SKIP_MODEL=0
MODEL_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --no-model)   SKIP_MODEL=1 ;;
    --model-only) MODEL_ONLY=1 ;;
    -h|--help)    sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown flag: $arg (try --help)" >&2; exit 2 ;;
  esac
done

bold() { printf '\033[1m%s\033[0m\n' "$1"; }
warn() { printf '\033[33m%s\033[0m\n' "$1"; }
err()  { printf '\033[31m%s\033[0m\n' "$1"; }
ok()   { printf '\033[32m%s\033[0m\n' "$1"; }

listening() { lsof -ti ":$1" -sTCP:LISTEN >/dev/null 2>&1; }
# Readiness means "the CONFIGURED model answers", not "something answers":
# a leftover server on :8001 serving a different model used to pass this
# check and every later agent run then failed with a 404 (Codex review P1).
model_answers() { curl -s -m 5 "http://localhost:${MODEL_PORT}/v1/models" 2>/dev/null | grep -qF "\"${MODEL_NAME}\""; }

# ── 0. Dependencies present? ────────────────────────────────────────────────
# Skipped for --model-only: that mode brings up the model endpoint and exits, so
# demanding a backend venv or installing frontend packages would contradict it
# (and fails outright on a fresh checkout).
if [ "$MODEL_ONLY" -eq 0 ]; then
  if [ ! -x .venv-api/bin/python ]; then
    err "missing .venv-api — create it first:"
    echo "  python3.12 -m venv .venv-api && .venv-api/bin/pip install -r backend/requirements.txt"
    exit 1
  fi
  if [ ! -d node_modules ]; then
    warn "node_modules missing — running npm install"
    npm install || exit 1
  fi
fi

# ── 1. Model endpoint ───────────────────────────────────────────────────────
MODEL_STATE="skipped"
if [ "$SKIP_MODEL" -eq 0 ]; then
  bold "== model endpoint (:${MODEL_PORT}) =="
  if model_answers; then
    ok "model: already answering on :${MODEL_PORT}"
    MODEL_STATE="up"
  elif [ -f scripts/local-model.env ] || [ -n "${VLLM_SSH_HOST:-}" ]; then
    echo "model: nothing on :${MODEL_PORT} — starting server + tunnel (cold start ~2 min)"
    if scripts/local-model.sh up; then
      if model_answers; then
        ok "model: READY on :${MODEL_PORT}"
        MODEL_STATE="up"
      else
        warn "model: server reports ready but the tunnel isn't answering yet"
        MODEL_STATE="tunnel-lagging"
      fi
    else
      err "model: could not bring up the endpoint"
      MODEL_STATE="down"
    fi
  else
    warn "model: no scripts/local-model.env and no VLLM_SSH_HOST — skipping"
    warn "  (copy scripts/local-model.env.example, or use the in-app gear to pick a cloud model)"
    MODEL_STATE="unconfigured"
  fi
  echo
fi

if [ "$MODEL_ONLY" -eq 1 ]; then
  [ "$MODEL_STATE" = "up" ] && exit 0 || exit 1
fi

# MODEL_PROVIDER / MODEL_NAME are resolved at the top of this script (one
# model identity shared with local-model.sh via scripts/local-model.env).
: "${OPENAI_BASE_URL:=http://localhost:${MODEL_PORT}/v1}"
: "${OPENAI_API_KEY:=not-needed}"
export MODEL_PROVIDER MODEL_NAME OPENAI_BASE_URL OPENAI_API_KEY

# ── 2. Backend ──────────────────────────────────────────────────────────────
bold "== backend (:${BACKEND_PORT}) =="
BACKEND_PID=""
if listening "$BACKEND_PORT"; then
  warn "backend: already running on :${BACKEND_PORT} — reusing it"
  warn "  NOTE: a backend started before your last code change is running STALE code."
  warn "  Stop it and re-run this script if you just edited backend/."
else
  .venv-api/bin/python -m uvicorn backend.server:app --host 127.0.0.1 --port "$BACKEND_PORT" &
  BACKEND_PID=$!
  for _ in $(seq 1 40); do
    curl -s -m 2 -o /dev/null "http://127.0.0.1:${BACKEND_PORT}/health" && break
    sleep 0.5
  done
  if curl -s -m 2 -o /dev/null "http://127.0.0.1:${BACKEND_PORT}/health"; then
    ok "backend: READY on :${BACKEND_PORT}"
  else
    err "backend: failed to start — see the output above"
    [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null
    exit 1
  fi
fi

cleanup() {
  [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null
}
trap cleanup EXIT

# ── 3. The check that actually matters ──────────────────────────────────────
# Ask the BACKEND whether its configured provider works. This is authoritative:
# an in-app model choice overrides every env var set above, so a reachable
# :8001 does not by itself prove the agent can run.
echo
bold "== agent model reachable? =="
CFG=$(curl -s -m 5 "http://127.0.0.1:${BACKEND_PORT}/config/model" 2>/dev/null)
TEST=$(curl -s -m 30 -X POST "http://127.0.0.1:${BACKEND_PORT}/config/test" \
       -H 'content-type: application/json' -d '{}' 2>/dev/null)
echo "config: ${CFG:-<no response>}"
if printf '%s' "$TEST" | grep -q '"ok":true'; then
  ok "model call: OK — agent runs will work"
else
  err "model call: FAILING — ${TEST:-<no response>}"
  echo
  err "Agent runs will fail with 'provider error: Connection error.'"
  echo "The viewer, editor and manual crop-box all still work. To fix the agent:"
  echo
  echo "  1. Is the tunnel up?      scripts/local-model.sh status"
  echo "  2. Server up, tunnel down => a VPN blip killed it. Reconnect the VPN, then:"
  echo "                              scripts/local-model.sh up"
  echo "  3. Prefer a cloud model?  open the gear icon in the app and pick one"
  echo
fi

# ── 4. Frontend ─────────────────────────────────────────────────────────────
echo
bold "== frontend (:${VITE_PORT}) =="
if listening "$VITE_PORT"; then
  warn "vite: already running on :${VITE_PORT} — reusing it (Ctrl-C here won't stop it)"
  echo
  ok "open http://localhost:${VITE_PORT}/"
  echo "Backend runs in the foreground; Ctrl-C stops what this script started."
  wait
else
  echo
  ok "open http://localhost:${VITE_PORT}/  (editor)  ·  add #/analyze for the analyst"
  echo
  npm run dev
fi
