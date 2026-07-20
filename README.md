# SplatAgent (GeoSplat Inspector)

## Quick start

The fastest path — one command, no Python version juggling:

```bash
GEMINI_API_KEY=... docker compose up   # http://localhost:8000
```

Or run frontend/backend natively (backend needs **Python 3.12** — `open3d`
has no wheel for newer Pythons yet):

```bash
# Frontend
npm install
npm run dev                # http://localhost:5173

# Backend (separate terminal, Python 3.12)
python3.12 -m venv backend/.venv-api && source backend/.venv-api/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.server:app --reload
```

Open the app, drop in a `.ply` scene (or pick a sample), click the **gear
icon** in the top bar, choose a provider, and paste an API key — no `.env`
editing required. Google Gemini has a free tier and is the recommended first
pick; see [Model backends](#model-backends) below for the full menu, including
a fully free/local option.

---

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

The easiest way to pick a model is the **in-app model picker** (gear icon,
top bar) — choose a provider, paste a key if it needs one, hit Test, Save.
No `.env` editing, no restart.

For power users, the same choice is also available via env — the provider is
chosen by `MODEL_PROVIDER`, so swapping backends is a config change, not a
code change (a saved in-app choice takes precedence over env). Pick a path:

| Path | When | Env |
|------|------|-----|
| **1. Gemini** (default, cloud) | Zero-config polished demo, free tier | `MODEL_PROVIDER=gemini`, `GEMINI_API_KEY=...` |
| **2. Any OpenAI-compatible API** (cloud) | OpenAI, OpenRouter, Together, … | `MODEL_PROVIDER=openai`, `MODEL_NAME=...`, `OPENAI_API_KEY=...` |
| **3. Local / self-hosted** (vLLM, Ollama, LM Studio) | Free, private, runs on your own GPU | `MODEL_PROVIDER=openai`, `OPENAI_BASE_URL=http://localhost:8001/v1`, `OPENAI_API_KEY=not-needed` |

One mechanism (`OPENAI_BASE_URL`) turns the OpenAI provider into a universal
OpenAI-compatible client. See `backend/.env.example` for the full menu.

> The agent is **vision-driven** — it *sees* the splats via captured frames and
> calls viewer tools. For Path 2/3 use a **vision** model (VLM); a text-only model
> is blind to the scene.

Setting up Path 3 (a self-hosted model on your own GPU)? See
[`docs/self-hosted-vllm.md`](docs/self-hosted-vllm.md) for the full runbook.

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
