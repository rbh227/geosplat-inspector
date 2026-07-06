---
title: "Backend/frontend coordinate space and edit-guard gotchas (SplatAgent)"
date: 2026-06-29
problem_type: architecture_pattern
track: knowledge
category: architecture-patterns
status: confirmed-root-cause-fix-pending
module: ["viewer", "agent", "analysis"]
tags: ["gaussian-splatting", "coordinate-systems", "three.js", "camera", "agent-loop", "cleanup"]
files:
  - "src/viewer/SceneManager.ts"
  - "frontend/src/agent/executors.ts"
  - "frontend/src/agent/overlay.ts"
  - "backend/agent/loop.py"
  - "backend/agent/verify.py"
---

# Backend/frontend coordinate space and edit-guard gotchas (SplatAgent)

> **Status:** both root causes were confirmed by code inspection during a debug session on 2026-06-29 but the fixes were **not yet applied**. This is captured as durable guidance so the lessons aren't re-discovered; verify against current code before relying on line references.

## Context

SplatAgent splits work across a Python backend (numpy, PLY coordinate space) and a TypeScript/Three.js frontend (render world space). Two recurring classes of bug live exactly at that seam. Both presented to the user as "the agent feels clunky and broken" / "outdoor scenes look really off," and both were invisible on the small sphere demos — they only surface on real, large, messy captures (e.g. `public/demos/train.ply`).

## Guidance

### 1. Backend and frontend must share ONE coordinate transform — apply it to *every* derived point, not just some

The splat mesh is rendered with `mesh.rotation.x = Math.PI` (`src/viewer/SceneManager.ts`) to convert COLMAP **Y-down** → Three.js **Y-up**. A 180° rotation about X negates **both Y and Z**: a backend point `(x, y, z)` is rendered at world `(x, −y, −z)`.

The bug: the **marker overlay** correctly compensates (`frontend/src/agent/overlay.ts` sets `markersGroup.rotation.x = Math.PI` so markers land on the splats), but the **agent camera executors** (`frontend/src/agent/executors.ts` — `orbit`, `look_at`, `frame_object`) take backend-supplied PLY-space coordinates and apply them **raw** as Three world coordinates. So the agent aims/orbits around a mirrored `(x, −y, −z)` point — the subject sits off-frame and `orbit` traces an erratic "messy circle" that barely moves the subject.

**Lesson:** when a render applies an orientation flip to the data, *every* coordinate that crosses the backend→frontend seam (camera targets, orbit centers, framing boxes, markers, picks) must pass through the *same* transform. Centralize it in one helper (e.g. `toRenderSpace([x,y,z]) -> (x,−y,−z)`) and route all of them through it. A partial fix (markers flipped, camera not) is worse than none because it looks intentional. Symptom to recognize: one overlay lands correctly while another is mirrored.

**Detection tip:** framing computed from the *actual rendered splats* (sampling `packedSplats` and transforming through `matrixWorld`, as the load-time framing does) is immune, because it never leaves render space. Only values that originate in backend/PLY space and are consumed directly by the frontend are affected — that asymmetry is the tell.

### 2. A blanket "reverted >X% of the scene" guard is wrong for majority-noise scenes

`backend/agent/loop.py` auto-undoes any edit that fails `silhouette_intact` (`backend/agent/verify.py`, `max_drop = 0.5`) — i.e. any edit removing more than 50% of the Gaussians. The intent was to stop the floater-cleanup loop from nuking the subject.

The bug: on a real outdoor capture the **noise is the majority**. `train.ply` measured 39% near-transparent floaters + 32% needles; correctly stripping background/floaters removes well over half the scene, so the guard reverts it and the user sees "cleanup did nothing."

**Lesson:** "removed a lot of Gaussians" is not the same as "destroyed the subject." Guard the thing you actually care about — the dense, high-opacity **subject core** surviving (e.g. via a multi-view silhouette check or an opacity/density-core retention metric) — not a fixed fraction of the raw count. A count-fraction guard silently assumes the subject is the majority of the scene, which is false for unbounded/outdoor captures.

## Why This Matters

Both bugs are the same shape: an assumption that holds for a small, clean, centered object (sphere demos) silently breaks for a large, noisy, off-center one (real outdoor scene). They compound into "the agent can't do anything" because the user can't *see* the scene well (bug 1) and can't *clean* it (bug 2) — so the tool's two core promises both fail exactly when they matter most.

## When to Apply

- Adding any backend-computed point that the frontend will use for camera, framing, or overlay placement → route it through the shared flip.
- Adding or tuning any automatic edit-revert/safety guard → express it in terms of subject survival, not raw count deltas.
- Reproducing "looks off" / "feels broken" reports → test on a **large messy** scene, not the demos; small clean scenes hide both classes of bug.
