# Analyst Scene Understanding — Design

**Date:** 2026-07-28
**Status:** approved, ready for planning

Refocuses the product on the Understand stage. The editor and its Clean-stage
agent (`docs/superpowers/specs/2026-07-25-operator-crop-box-design.md` and
predecessors) stay exactly as they are — they become the *preparation* step,
not the headline.

---

## 1. Problem

The agent's editing surface is built, tested, and working. Its scene
*understanding* is not: `CLAUDE.md` has carried "live-model counting accuracy
on real post-disaster scenes needs manual iteration" as an open item for
weeks, and no structural work has been done to earn that accuracy.

Two concrete defects explain most of it.

**The prompt instructs a counting method that cannot work.** The Understand
prompt says: *"For 'how many X' questions: capture 3-4 views from different
angles, count what is visible, and answer with the count."* Meanwhile
`backend/agent/loop.py:206` clears `_pending_frames` after every model call,
and the OpenAI adapter attaches images to the last user turn only
(`backend/providers/openai.py:108`). The model therefore never holds two views
at once. It sees view 1, writes "4 houses," then sees view 3 — the same houses
from a new angle — with no image of view 1 to compare against. It can only
add. Multi-view counting without visual memory or geometric deduplication is a
double-counting machine; a 13-building scene can plausibly return 20+.

**Loading a scene freezes the viewer.** `POST /scene`
(`backend/api/routes.py:102`) runs full k-NN metrics over every splat on every
upload — the handler's own comment says "minutes on a 2M-splat scene." It runs
in a thread, so the event loop survives, but it saturates CPU cores while
SparkJS sorts splats on the CPU. Observed 2026-07-28: the scene renders, then
frame rate collapses for minutes, then recovers. The analyst never uses those
metrics — it answers from pixels.

## 2. Goals

1. **A separate analyst window** at `#/analyze`, look-only, working on the
   scene the editor has already cleaned.
2. **Reliable scene understanding** on one target scene: say what the imagery
   shows, count the structures with honest certainty tiers, and report
   condition without inventing damage.
3. **No hardcoded domain.** The prompt teaches how to look, not what to
   expect.

**Non-goals:** visual memory across turns (rejected — see §8); grounded
bounding boxes with 3D deduplication (deferred — see §8); multi-scene
evaluation; damage severity scoring; the offline reconstruction pipeline
(separate project).

## 3. Target scene and answer key

`public/demos/iona_park.ply` — 2M splats — is the single target. Everything in
this spec is validated against it.

**Ground truth (operator-provided, 2026-07-28):**

- Aerial capture of a low-cost / trailer-park housing area.
- **13 buildings total**: 8 clearly resolvable in the main frame, ~5 further
  back in the background.
- **No major damage.** All structures are standing.

**The target answer**, approximately:

> This is aerial imagery of a low-density residential area — small single-story
> homes on a shared lot. I can clearly see 8 homes in the main frame, with
> roughly 5 more further back that are harder to resolve — about 13 structures
> in total. All appear to be standing; I don't see major damage.

This sentence is the acceptance criterion. It is reachable from **one
well-framed capture**; it does not require a flight.

## 4. Prerequisite: stop running metrics on upload

Making metrics lazy is a precondition for demoing on a 2M-splat scene — the
lag lands on every load.

`POST /scene` returns `UploadResponse(id, metrics)`. Change it to return
`UploadResponse(id, count)` — `Scene.count()` is a cheap alive-count already
used by `SceneState.__init__` — and move the k-NN metrics behind the existing
`GET /metrics`, which already computes on demand. Callers that want metrics
ask for them; the analyst never does.

(`bounds()` is on the `SplatModel` protocol but not exposed on the engine
`Scene` wrapper, so the upload response carries the count only.)

The change is low-risk: `src/backend/client.ts:21` declares `metrics:
Record<string, unknown>` on the upload response, but the only caller
(`registerScene` in `src/App.tsx:315`) destructures `{ id }` and ignores it.
The field is declared and unused.

This is still a contract change to `UploadResponse` and needs the mirrors in
`backend/contracts/` and `frontend/src/contracts.ts` kept in sync — including
the comment at `frontend/src/contracts.ts:121` that documents the response as
`{ id, metrics }` — with the registry drift-guard tests updated.

## 5. The analyst window

### 5.1 Routing

Hash-based: `#/analyze?scene=<id>`, with the editor at the default route. A
path route would require adding react-router plus SPA-fallback configuration
on the dev server and any future static host; a hash route needs neither and
costs about a dozen lines. Swapping in a real router later is mechanical.

### 5.2 Handoff

The editor's top bar gets an **Analyze scene** action, enabled only when a
backend scene is registered. It opens `#/analyze?scene=<current-id>` in a new
window.

The analyst reads the id from the URL, loads the scene via the existing
`scenePlyUrl(sceneId)` — which serves *the current alive set*, i.e. the
post-edit scene — and adopts `GET /ids` so its ID space matches the backend's.
Reloading the analyst picks up any cleanup done since.

The id travels in the URL, not `sessionStorage`. `src/persistence.ts` already
persists exactly this record, but sessionStorage is per-tab: a new window
starts empty.

### 5.3 Missing-scene state

If `GET /ids` 404s for the id — backend restarted, scenes are in-memory only —
the analyst shows a "that scene is no longer loaded" state with a file drop
zone, never a hung spinner. This mirrors the guard the editor's restore path
already has, and it is a real case: observed 2026-07-28 when the backend
process was replaced under a live browser session.

### 5.4 What the analyst does not have

No tool rail, selection tools, edit history, export, or proposals. The
Understand stage already enforces look-only at both the spec level
(`stage_tools`) and the dispatch level; the window simply stops rendering the
editing UI.

### 5.5 Splitting App.tsx

`src/App.tsx` is 981 lines wiring the editor, the agent, persistence, and
history. Adding a second page to it is not viable.

Extract the shared scene/viewer concerns — load, register, persist,
reload-authoritative, ID adoption, status reporting — into a hook that both
pages consume, leaving two thin page shells: the editor (tool rail, Clean
agent, proposals) and the analyst (viewport, chat, captures).

This is scoped to what the split requires. The editor's internal behavior is
not otherwise refactored.

## 6. Analyst behavior

### 6.1 Framing: one good frame

For "what is this" and "how many X" questions:

1. **Establish the frame.** Capture once and read the percept already returned
   (`frontend/src/agent/types.ts:PerceptTag`). If `in_view` is false, turn
   toward the scene — `coverage` is meaningless until then. If `coverage`
   exceeds ~0.75 the camera is too close to see the whole site: dolly back.
   Below ~0.3: dolly in. Target 0.45–0.75.
2. **Count from that single frame.** One capture, one count.
3. **Move only to resolve a named ambiguity** — "is that one long building or
   two?" — re-examining a *known* object.

**The governing rule, stated explicitly in the prompt: the count comes from
one frame; other views may only correct that count, never extend it.** This is
what removes the double-counting.

No "fit the whole scene" action is added. `set_view` / `frame_object` /
`reset_view` were removed from both stages on purpose
(`docs/plans/2026-07-20-001`) so the agent anchors to the operator's view and
maneuvers relatively; reintroducing one for framing would undo that. The agent
works from where the operator put it, using `dolly` nudges and `reframe` to
recover.

**Accepted trade-off:** answer quality depends on the operator's framing.
Framed tight on the main cluster, the honest answer becomes "8 homes, more
continuing off-frame" — correct, but not the full 13. This failure mode is
honest rather than confabulated, and it means the demo has a framing step.

### 6.2 Answer shape

Three moves:

**1. What this is.** Modality and setting, from pixels: "aerial imagery of a
low-density residential area — single-story homes on small lots."

**2. What's countable, tiered by certainty.** "8 homes clearly visible in the
foreground; roughly 5 more further back, harder to resolve — about 13
structures total."

Tiering is the design's honesty mechanism. A single number from a small model
on a 1024px frame is a bluff; "8 clear, ~5 distant" is more accurate, more
useful, and degrades gracefully when framing is poor.

**3. Condition, with restraint.** Two hard rules:

- **No damage claim without a locatable referent.** Not "some structures are
  damaged" but "the roof on the northeast home is missing" — or nothing.
  Unlocatable damage is hallucinated damage.
- **Reconstruction artifacts are not damage.** Holes, smearing, floaters, and
  missing geometry are splat quality problems and must be named as such, never
  as collapse or destruction. On Iona Park, where nothing is damaged, this is
  the most likely false positive.

And explicitly: **"no major damage; all structures appear standing" is a good
answer.** Small models pattern-match "assess damage" into finding damage. The
prompt must make "nothing is wrong here" a first-class result.

### 6.3 Domain neutrality

The prompt teaches how to look — establish framing, tier by certainty, locate
before claiming — and says nothing about disasters, trailers, or what these
scenes usually contain. No prior that damage is likely. Pointed at an intact
suburb, a construction site, or a forest, the same instructions produce a
sensible answer. Iona Park is the test case, not a baked-in assumption.

## 7. Changes by file

**Backend**

- `backend/agent/system_prompt.py` — rewrite `_UNDERSTAND_PROMPT`: remove the
  "capture 3-4 views from different angles" counting instruction; add the
  one-frame counting rule, the certainty tiering, the locatable-referent rule,
  the artifacts-are-not-damage rule, and "no damage found" as a valid result.
  Rewrite the `count_objects` skill recipe to match. Re-scope `describe_scene`
  and `survey_scene` so neither implies multi-view counting.
- `backend/api/routes.py` — `POST /scene` no longer computes k-NN metrics (§4).
- `backend/contracts/` — `UploadResponse` shape change, mirrored.

**Frontend**

- `src/main.tsx` — hash route dispatch (the app entry, per `index.html:24`).
- `src/App.tsx` — split into a shared scene hook plus editor and analyst page
  shells (§5.5).
- new analyst page — viewport, chat, capture display, missing-scene state.
- `src/ui/TopBar.tsx` — "Analyze scene" action.
- `frontend/src/contracts.ts` — `UploadResponse` mirror.

## 8. Rejected and deferred

**Rejected — visual memory across turns.** Persisting captured frames so the
model can compare views would multiply image tokens per call. On a local 8B
model with bounded GPU headroom — capture resolution already had to be capped
once (`ca10f06`) — this is as likely to hurt as help, and §6.1 removes the need
for it.

**Deferred — grounded boxes with 3D deduplication.** Having Qwen3-VL emit
bounding boxes per detection, unprojecting them against splat geometry, and
merging detections across views by 3D position is the only approach that makes
a multi-view count provably correct, and it would give clickable, verifiable
results. It is also weeks of work — unprojection, association thresholds,
total dependence on the small model's grounding accuracy. Revisit if the
one-frame approach proves the concept and counts need to be defensible.

## 9. Testing

Following the house pattern in `backend/agent/tests/test_analyst_prompt.py`:
structural CI proxies, with answer quality evaluated manually.

**Prompt guards** — the Understand prompt does not instruct multi-angle
counting; it does contain the one-frame rule, the tiering instruction, and the
locatable-referent rule. `count_objects`'s recipe does not ask for 3–4 views.

**Structural** — a scripted counting run captures and answers with zero edit,
metrics, or teleport calls (extends the existing test).

**Upload** — `POST /scene` returns without computing k-NN metrics; `GET
/metrics` still does. Contract drift guards updated on both sides.

**Frontend** — hash route resolves `#/analyze?scene=<id>` to the analyst page;
the analyst loads by scene id and adopts ids; a 404 renders the missing-scene
state, not a spinner; the editor's "Analyze scene" action is gated on a
registered scene.

**Manual, on Iona Park** — the §3 answer key. Frame the site, ask "what am I
looking at?" and "how many buildings?", and check: modality and setting named;
foreground count near 8; background acknowledged as approximate; total near
13; no invented damage; no artifact described as destruction.

## 10. Open questions

- **Other demo scenes.** The operator said the other scenes can go. They total
  ~1.2GB (`bldg01_house`, `raw`, `scene`, `trailer_full`). Deleting them is not
  part of this work; confirm separately before removing anything.
- **Model availability.** The local vLLM at `localhost:8001` is down. Nothing
  in §6 can be validated live until it is back.
