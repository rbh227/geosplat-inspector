# SplatAgent (GeoSplat Inspector)

A local splat **editor** where an AI agent works the same visible tools a human
does. Load a 3D Gaussian Splatting (`.ply`) scene, then work in two stages:

- **Clean** — a classic editor (SuperSplat-style selection grammar: brush, lasso,
  polygon, sphere, box → delete/keep/undo; WASD fly navigation with an on-screen
  pad). Prompt the cleanup agent and *watch* it fly and select — the pad lights
  up, selection volumes flash before committing — or grab the tools yourself at
  any moment (manual input pauses the agent; Resume/Stop from the banner).
- **Understand** — a look-only analyst: it flies, captures views, and answers
  scene questions ("how many damaged buildings?") from what is visible. No
  editing tools are even offered to it.

Agent capabilities are packaged as **skills** (survey_scene, clean_floaters,
count_objects, …): one vocabulary the agent composes autonomously and you can
click in the chat panel. A Python (FastAPI) backend owns the data, editing
history, and agent loop; a React + Vite + SparkJS frontend renders the splats
and acts as the agent's eyes and hands. Human and agent edits share one undo
history keyed by stable splat IDs.

## Model backends

The agent is model-agnostic. The provider is chosen by env (`MODEL_PROVIDER`), so
swapping backends is a config change, not a code change. Pick a path:

| Path | When | Env |
|------|------|-----|
| **1. Gemini** (default, cloud) | Zero-config polished demo | `MODEL_PROVIDER=gemini`, `GEMINI_API_KEY=...` |
| **2. Any OpenAI-compatible API** (cloud) | OpenAI, OpenRouter, Together, … | `MODEL_PROVIDER=openai`, `MODEL_NAME=...`, `OPENAI_API_KEY=...` |
| **3. Local / self-hosted** (vLLM, Ollama, LM Studio) | Cheap, private, runs on your own GPU | `MODEL_PROVIDER=openai`, `OPENAI_BASE_URL=http://localhost:8001/v1`, `OPENAI_API_KEY=not-needed` |

One mechanism (`OPENAI_BASE_URL`) turns the OpenAI provider into a universal
OpenAI-compatible client. See `backend/.env.example` for the full menu.

> The agent is **vision-driven** — it *sees* the splats via captured frames and
> calls viewer tools. For Path 2/3 use a **vision** model (VLM); a text-only model
> is blind to the scene.

### Local vLLM runbook (Path 3)

Serve an open-source VLM on a CUDA GPU, bind it to localhost, and SSH-tunnel it to
your machine. Tool-calling is **off by default** in vLLM — the `--enable-auto-tool-choice`
and `--tool-call-parser hermes` flags are required or the agent gets prose and takes
no actions. Keep `--max-model-len` large (32768): a captured frame costs thousands
of image tokens, and a small window (e.g. 8192) returns HTTP 400 "decoder prompt is
longer than the maximum model length" on any vision turn.

```bash
# On the GPU box (in your own venv). Pin vLLM to a build matching the box's CUDA
# (e.g. driver CUDA 12.x -> a cu12 vLLM such as 0.10.2; the newest pulls cu13).
python -m venv ~/.venvs/vllm && source ~/.venvs/vllm/bin/activate
pip install "vllm==0.10.2"

# Pick an IDLE gpu (nvidia-smi), pin it, and cap the card you claim.
CUDA_VISIBLE_DEVICES=0 vllm serve Qwen/Qwen2.5-VL-7B-Instruct \
  --host 127.0.0.1 --port 8000 \
  --gpu-memory-utilization 0.90 \
  --max-model-len 32768 \
  --enable-auto-tool-choice --tool-call-parser hermes \
  --chat-template /path/to/examples/qwen2_5_vl_tool_chat_template.jinja
```

```bash
# On your Mac: tunnel LOCAL 8001 -> the box's 8000 (the backend owns 8000 locally),
# then set backend/.env to Path 3 with OPENAI_BASE_URL=http://localhost:8001/v1.
ssh -N -L 8001:127.0.0.1:8000 you@gpu-box
```

---

## Frontend (React + TypeScript + Vite)

This template provides a minimal setup to get React working in Vite with HMR and some ESLint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the ESLint configuration

If you are developing a production application, we recommend updating the configuration to enable type-aware lint rules:

```js
export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      // Other configs...

      // Remove tseslint.configs.recommended and replace with this
      tseslint.configs.recommendedTypeChecked,
      // Alternatively, use this for stricter rules
      tseslint.configs.strictTypeChecked,
      // Optionally, add this for stylistic rules
      tseslint.configs.stylisticTypeChecked,

      // Other configs...
    ],
    languageOptions: {
      parserOptions: {
        project: ['./tsconfig.node.json', './tsconfig.app.json'],
        tsconfigRootDir: import.meta.dirname,
      },
      // other options...
    },
  },
])
```

You can also install [eslint-plugin-react-x](https://github.com/Rel1cx/eslint-react/tree/main/packages/plugins/eslint-plugin-react-x) and [eslint-plugin-react-dom](https://github.com/Rel1cx/eslint-react/tree/main/packages/plugins/eslint-plugin-react-dom) for React-specific lint rules:

```js
// eslint.config.js
import reactX from 'eslint-plugin-react-x'
import reactDom from 'eslint-plugin-react-dom'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      // Other configs...
      // Enable lint rules for React
      reactX.configs['recommended-typescript'],
      // Enable lint rules for React DOM
      reactDom.configs.recommended,
    ],
    languageOptions: {
      parserOptions: {
        project: ['./tsconfig.node.json', './tsconfig.app.json'],
        tsconfigRootDir: import.meta.dirname,
      },
      // other options...
    },
  },
])
```
