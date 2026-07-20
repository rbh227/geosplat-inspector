# Self-hosted vLLM runbook (Path 3: local / free models)

Serve an open-source vision-language model (VLM) on your own CUDA GPU, bind it
to localhost, and SSH-tunnel it to the machine running SplatAgent. This is the
free-model path — see the README's model-backend table for the alternatives.

Tool-calling is **off by default** in vLLM — the `--enable-auto-tool-choice`
and `--tool-call-parser hermes` flags are required or the agent gets prose and
takes no actions. Keep `--max-model-len` large (32768): a captured frame costs
thousands of image tokens, and a small window (e.g. 8192) returns HTTP 400
"decoder prompt is longer than the maximum model length" on any vision turn.

```bash
# On the GPU box (in your own venv). Pin vLLM to a build matching the box's
# CUDA driver (e.g. driver CUDA 12.x -> a cu12-era vLLM; the newest releases
# may pull cu13 and fail to load on an older driver).
python -m venv ~/.venvs/vllm && source ~/.venvs/vllm/bin/activate
pip install vllm

# Pick an IDLE gpu (nvidia-smi), pin it, and cap the card you claim.
CUDA_VISIBLE_DEVICES=0 vllm serve Qwen/Qwen2.5-VL-7B-Instruct \
  --host 127.0.0.1 --port 8000 \
  --gpu-memory-utilization 0.90 \
  --max-model-len 32768 \
  --enable-auto-tool-choice --tool-call-parser hermes \
  --chat-template /path/to/examples/qwen2_5_vl_tool_chat_template.jinja
```

```bash
# On your machine: tunnel LOCAL 8001 -> the box's 8000 (SplatAgent's backend
# owns 8000 locally), then either set backend/.env to Path 3 with
# OPENAI_BASE_URL=http://localhost:8001/v1, or use the in-app model picker
# (gear icon) and pick "Local model" with that same URL — no env editing needed.
ssh -N -L 8001:127.0.0.1:8000 you@your-gpu-box
```

## Convenience script

`scripts/local-model.sh up|down|status` wraps the above into an on-demand
workflow for shared GPU boxes: start the server + a self-healing tunnel only
for a test/demo session, then `down` to free the card for others. Copy
`scripts/local-model.env.example` to `scripts/local-model.env` (gitignored)
and set `VLLM_SSH_HOST=you@your-gpu-box` first.

## Newer models

`Qwen/Qwen2.5-VL-7B-Instruct` above is the smallest reliable baseline. If your
GPU has more headroom, later Qwen VL releases (e.g. `Qwen3-VL`) generally do
better on agentic tool-calling and spatial reasoning — check current vLLM
version compatibility for your driver before switching, and note that some
model+quantization combinations need a specific `--gpu-memory-utilization` /
`--max-model-len` balance to fit in one card's KV cache.
