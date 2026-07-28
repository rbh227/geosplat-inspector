# Iona Park — Analyst Answer Key

**Scene:** `public/demos/iona_park.ply` (2,000,000 splats)
**Status:** answer key recorded; **baseline run not yet performed**
**Design:** `docs/superpowers/specs/2026-07-28-analyst-scene-understanding-design.md`

This is the single scene the analyst is validated against. Without it, "the
answers seem better" is unfalsifiable — every prompt change gets compared here.

---

## 1. Ground truth

Operator-provided, 2026-07-28:

- **What it is:** aerial capture of a low-cost / trailer-park housing area.
- **Structures: 13 total** — 8 clearly resolvable in the main frame, ~5 further
  back in the background.
- **Damage: none major.** All structures are standing.

## 2. The target answer

Roughly this, in the analyst's own words:

> This is aerial imagery of a low-density residential area — small single-story
> homes on a shared lot. I can clearly see 8 homes in the main frame, with
> roughly 5 more further back that are harder to resolve — about 13 structures
> in total. All appear to be standing; I don't see major damage.

Reachable from **one well-framed capture**. It does not require a flight.

## 3. Procedure

1. Backend on `:8000`, Vite on `:5173`, and a live model.
   Confirm the model first — this is the usual blocker:
   ```bash
   curl -s -m 5 http://localhost:8001/v1/models
   curl -s -X POST http://127.0.0.1:8000/config/test \
        -H 'content-type: application/json' -d '{}'
   ```
   Expect a model list and `{"ok":true,...}`.
2. Load `iona_park.ply` in the editor. Confirm the viewer does **not** freeze
   after render (regression check on the lazy-metrics fix).
3. Frame the whole site so every structure is visible, then click
   **Analyze scene**.
4. In the analyst window, ask in turn:
   - `what am I looking at?`
   - `how many buildings are in this scene?`

**Framing matters.** The count comes from one frame by design, so a tight crop
on the main cluster makes "8 homes, more continuing off-frame" the *correct*
answer. Frame wide before asking.

## 4. Scoring

| # | Criterion | Result |
|---|---|---|
| 1 | Names modality and setting (aerial, residential) before counting | — |
| 2 | Foreground count is near 8 | — |
| 3 | Background structures acknowledged as approximate, not omitted and not counted confidently | — |
| 4 | Total near 13 — and critically **not 20+** | — |
| 5 | No invented damage | — |
| 6 | No reconstruction artifact described as collapse or destruction | — |

**Criterion 4 is the one this whole design exists for.** The old prompt asked
for 3–4 viewpoints and a count across them, while captured frames never
survived a model turn — so the agent could only add, never reconcile. A 20+
answer means the double-counting is back.

**Criterion 5–6 are the demo-embarrassment guards.** Nothing here is damaged.
A small model asked to "assess damage" will tend to find some, and splat
artifacts (holes, smearing, floaters) are the most likely thing it mistakes for
destruction.

## 5. Baseline run

*Not yet performed — the local vLLM at `localhost:8001` was down on 2026-07-28.*

When run, record verbatim below: the exact questions, the model's full answers,
and the scoring table filled in. That becomes the comparison point for every
later prompt change.

```
model:
date:
Q1: what am I looking at?
A1:

Q2: how many buildings are in this scene?
A2:
```
