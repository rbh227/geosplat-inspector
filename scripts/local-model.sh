#!/usr/bin/env bash
# On-demand vLLM serving for the SplatAgent local-model path.
#
# The model server claims a full GPU (~22 GB VRAM) only while it runs, so on a
# shared box: `up` before a test/demo session, `down` right after. Weights stay
# in the server's disk cache — a cold `up` takes ~2 minutes.
#
#   scripts/local-model.sh up       start server on the GPU host + SSH tunnel, wait until ready
#   scripts/local-model.sh down     stop server + tunnel, verify the GPU is freed
#   scripts/local-model.sh status   show server / tunnel / GPU state
#
# Set VLLM_SSH_HOST (or create scripts/local-model.env, gitignored) to point
# this at your own GPU host, e.g. VLLM_SSH_HOST=you@your-gpu-box.

set -euo pipefail

ENV_FILE="$(dirname "$0")/local-model.env"
[ -f "$ENV_FILE" ] && source "$ENV_FILE"

SSH_HOST="${VLLM_SSH_HOST:?set VLLM_SSH_HOST=you@your-gpu-box, or create scripts/local-model.env with VLLM_SSH_HOST=... (see scripts/local-model.env.example)}"
GPU_ID="${VLLM_GPU_ID:-0}"
MODEL="${VLLM_MODEL:-Qwen/Qwen3-VL-8B-Instruct-FP8}"
VENV="${VLLM_VENV:-~/.venvs/vllm-qwen3}"
REMOTE_PORT="${VLLM_REMOTE_PORT:-8000}"   # server-side, bound to 127.0.0.1
LOCAL_PORT="${VLLM_LOCAL_PORT:-8001}"     # Mac-side (FastAPI backend owns 8000)
TMUX_SESSION="${VLLM_TMUX_SESSION:-vllm-qwen3}"
REMOTE_LOG="${VLLM_REMOTE_LOG:-~/vllm_qwen3.log}"
# Memory budget on a 24GB card, tuned against two opposite failures:
#   - at 0.92 / 32768, a single full-resolution viewport capture (2044x1316 ->
#     13,724 patches) OOM'd inside qwen3_vl._process_image_input and killed the
#     engine mid-run: the KV cache is reserved up-front, the vision tower
#     allocates per-request, and only 49 MiB was left for a 122 MiB allocation.
#   - at 0.85 / 32768 the engine refuses to start at all: a 32768 context needs
#     4.50 GiB of KV cache and only 3.21 GiB is left after weights.
# 0.90 / 24576 clears both: ~1 GiB of KV headroom plus ~2.4 GiB of card left
# outside the budget for vision activations. The frontend also caps capture size
# (frontend/src/agent/capture.ts MAX_CAPTURE_EDGE), cutting that activation ~4x.
#
# A server-side pixel cap (--mm-processor-kwargs '{"max_pixels":...}') is
# deliberately NOT set here: the launch line below passes SERVE_ARGS through
# ssh -> remote sh -> tmux -> sh, and the JSON's quotes do not survive that many
# layers (vLLM would receive {max_pixels:1048576} and refuse to start). Set it
# via VLLM_SERVE_ARGS if you need it and can verify the quoting on your host.
SERVE_ARGS="${VLLM_SERVE_ARGS:---gpu-memory-utilization 0.90 --max-model-len 24576 --enable-auto-tool-choice --tool-call-parser hermes}"
TUNNEL_PATTERN="${LOCAL_PORT}:127.0.0.1:${REMOTE_PORT}"

ssh_run() { ssh -o BatchMode=yes -o ConnectTimeout=10 "$SSH_HOST" "$@"; }

tunnel_up() {
  if pgrep -f "ssh .*-L ${TUNNEL_PATTERN}" >/dev/null; then
    echo "tunnel: already running"
    return
  fi
  # Self-healing loop: survives VPN blips, reconnects when the route returns.
  nohup bash -c "while true; do ssh -N -o BatchMode=yes -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \
    -L ${TUNNEL_PATTERN} ${SSH_HOST}; sleep 3; done" >/dev/null 2>&1 &
  echo "tunnel: started (local :${LOCAL_PORT} -> remote :${REMOTE_PORT})"
}

tunnel_down() {
  pkill -f "ssh .*-L ${TUNNEL_PATTERN}" 2>/dev/null || true
  pkill -f "while true; do ssh .*${TUNNEL_PATTERN}" 2>/dev/null || true
  echo "tunnel: stopped"
}

case "${1:-}" in
  up)
    echo "== starting ${MODEL} on ${SSH_HOST} (GPU ${GPU_ID}) =="
    ssh_run "tmux has-session -t ${TMUX_SESSION} 2>/dev/null" && {
      echo "server: tmux session '${TMUX_SESSION}' already exists — reusing"; } || {
      ssh_run "rm -f ${REMOTE_LOG}; tmux new-session -d -s ${TMUX_SESSION} \
        'CUDA_VISIBLE_DEVICES=${GPU_ID} ${VENV}/bin/vllm serve ${MODEL} \
        --host 127.0.0.1 --port ${REMOTE_PORT} ${SERVE_ARGS} 2>&1 | tee ${REMOTE_LOG}'"
      echo "server: launched, waiting for readiness (cold start ~2 min)..."
    }
    for i in $(seq 1 45); do
      if ssh_run "curl -s -m 3 http://127.0.0.1:${REMOTE_PORT}/v1/models" | grep -q "$(basename "$MODEL")"; then
        echo "server: READY"
        tunnel_up
        sleep 2
        if curl -s -m 5 "http://localhost:${LOCAL_PORT}/v1/models" | grep -q "$(basename "$MODEL")"; then
          echo "tunnel: READY — backend can use http://localhost:${LOCAL_PORT}/v1"
        else
          echo "tunnel: started but not answering yet; retry 'status' in a few seconds"
        fi
        exit 0
      fi
      if ! ssh_run "tmux has-session -t ${TMUX_SESSION} 2>/dev/null"; then
        echo "server: CRASHED during startup — last log lines:" >&2
        ssh_run "tail -15 ${REMOTE_LOG}" >&2
        exit 1
      fi
      sleep 8
    done
    echo "server: timed out waiting for readiness — check: $0 status" >&2
    exit 1
    ;;
  down)
    ssh_run "tmux kill-session -t ${TMUX_SESSION} 2>/dev/null || true"
    tunnel_down
    sleep 5
    echo "== GPU ${GPU_ID} after shutdown =="
    ssh_run "nvidia-smi --query-gpu=index,memory.used --format=csv,noheader | sed -n '$((GPU_ID + 1))p'"
    ;;
  status)
    echo "== server =="
    ssh_run "tmux has-session -t ${TMUX_SESSION} 2>/dev/null && echo 'tmux: up' || echo 'tmux: down'; \
      curl -s -m 3 http://127.0.0.1:${REMOTE_PORT}/v1/models | head -c 120; echo; \
      nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader"
    echo "== tunnel =="
    pgrep -f "ssh .*-L ${TUNNEL_PATTERN}" >/dev/null && echo "tunnel: up" || echo "tunnel: down"
    curl -s -m 3 "http://localhost:${LOCAL_PORT}/v1/models" | head -c 120; echo
    ;;
  *)
    echo "usage: $0 {up|down|status}" >&2
    exit 1
    ;;
esac
