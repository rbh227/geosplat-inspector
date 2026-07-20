# GeoSplat Inspector — CPU-only image (no CUDA). One `docker compose up` runs
# the FastAPI backend and serves the built frontend on :8000.

# ── Stage 1: build the frontend (native arch — output is platform-agnostic JS) ──
FROM --platform=$BUILDPLATFORM node:22-slim AS frontend
WORKDIR /fe
COPY package.json package-lock.json ./
RUN npm ci
COPY tsconfig*.json vite.config.ts index.html ./
COPY src/ ./src/
COPY public/ ./public/
RUN npm run build      # -> /fe/dist

# ── Stage 2: backend runtime ──
# Pin amd64: open3d publishes manylinux x86_64 wheels but NO linux/arm64 wheel.
# On Apple Silicon this runs under emulation (wheel install only — no compile).
FROM --platform=linux/amd64 python:3.12-slim

# System deps for Open3D headless + scipy (CPU-only; no CUDA)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Backend source + example scenes
COPY backend/ ./backend/
COPY examples/ ./examples/

# Built frontend (served by FastAPI StaticFiles at "/")
COPY --from=frontend /fe/dist ./dist

EXPOSE 8000

# API keys come from env at runtime (see docker-compose.yml) — never baked in.
CMD ["uvicorn", "backend.server:app", "--host", "0.0.0.0", "--port", "8000"]
