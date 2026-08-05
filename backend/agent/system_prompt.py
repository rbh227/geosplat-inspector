"""Stage-aware system prompts, the skills vocabulary, and ToolSpec construction.

Two stages (R12, docs/plans/2026-07-05-001):
  - "clean":      the full editor surface — the agent operates the same visible
                  tools a human uses (selection, movement, edits).
  - "understand": look-only analyst — navigation + capture + answer; no editing
                  capability is offered to the model at all (R15).

Skills are prose vocabulary, NOT tool schemas (KTD7): named routines the model
composes from primitive tools. One list serves both invokers — it renders into
the system prompt here and is served to the chat panel's skill list (R11).

Tool specs are built from the tool registry (§6.5, v0.2) filtered by stage, so
the model's tool list can never drift from what the dispatcher can execute.
"""

from __future__ import annotations

from typing import Literal, TypedDict

from backend.contracts import ToolSpec
from backend.contracts.tools import TOOL_BY_NAME, TOOL_REGISTRY

Stage = Literal["clean", "understand"]

# ---------------------------------------------------------------------------
# Stage tool gating (KTD8). Understand is a strict allow-list: navigation,
# capture, display, movement, and answer. Everything else — selection,
# edits, history, export — is not offered and is rejected at dispatch.
# ---------------------------------------------------------------------------

# Teleport / absolute-coordinate camera tools. REMOVED from BOTH stages' offered
# sets (button-only relative nav, docs/plans/2026-07-20-001) so the agent starts
# at the operator's current view and cannot fling itself to a computed
# coordinate. Kept in the registry (the contract is additive); the loop backstop
# rejects any hallucinated call to one.
TELEPORT_TOOLS: frozenset[str] = frozenset(
    {"look_at", "set_view", "orbit", "frame_object", "reset_view", "capture_orbit"}
)

# v0.6 (app-owned survey, spec 2026-08-03): the app flies the camera and
# captures the survey views BEFORE the model's first turn — the model is
# offered no navigation or capture tools at all, so every navigation failure
# mode (lost camera, reframe loops, percept misreads) is structurally
# unreachable in the Understand stage.
UNDERSTAND_TOOLS: frozenset[str] = frozenset({"narrate", "answer"})

# App-dispatched only (v0.6 survey, v0.7 judgment-tour tint): the loop or the
# CleanupController sends these; the model must never see them as options.
# survey_capture was previously exposed in Clean by accident of "registry minus
# teleports" (tools.py says loop-dispatched only).
CONTROLLER_ONLY_TOOLS: frozenset[str] = frozenset({"survey_capture", "select_by_ids"})


def stage_tools(stage: Stage) -> frozenset[str]:
    """Tool names offered to the model in a stage."""
    if stage == "understand":
        return UNDERSTAND_TOOLS
    # Clean: the full editor surface MINUS the teleport tools (button-only nav)
    # MINUS the app-dispatched tools (the model never drives those).
    return frozenset(TOOL_BY_NAME) - TELEPORT_TOOLS - CONTROLLER_ONLY_TOOLS


# ---------------------------------------------------------------------------
# Skills vocabulary (KTD7) — one registry, two invokers (R10/R11).
# ---------------------------------------------------------------------------

class Skill(TypedDict):
    name: str
    stage: str  # "clean" | "understand" | "both"
    description: str
    recipe: str


SKILLS: list[Skill] = [
    {
        "name": "survey_scene",
        "stage": "clean",
        "description": "Look around the scene from where you are and get oriented.",
        "recipe": "From the operator's current view, alternate move_camera and turn to sweep the view; capture_frame every couple of moves; narrate what you see. Use this to get ORIENTED, never to count — counts come from one framed capture (see count_objects).",
    },
    {
        "name": "hover_around",
        "stage": "clean",
        "description": "Slow, watchable flight around what you're looking at.",
        "recipe": "Alternate move_camera holds (400-800 ms) and turn with scan_pause; capture_frame to check; narrate what you notice as you move.",
    },
    {
        "name": "frame_and_capture",
        "stage": "clean",
        "description": "Get a good look at a region and capture one clear view of it.",
        "recipe": "move_camera and turn until the region fills the view (dolly to zoom in), scan_pause ~500 ms, capture_frame.",
    },
    {
        "name": "clean_floaters",
        "stage": "clean",
        "description": "Find floaters and erase them with the selection tools.",
        "recipe": "list_problem_regions -> move_camera/turn until the worst region is in view -> capture_frame -> select_by_brush on the floaters you SEE (or select_by_sphere on a tight cluster) -> get_selection_state to sanity-check the count -> propose_decision(kind='delete_selection') -> delete_selection once approved -> verify with get_metrics + capture_frame.",
    },
    {
        "name": "trim_background",
        "stage": "clean",
        "description": "Isolate the subject and drop everything else.",
        "recipe": "No navigation needed — the box comes from the data. get_core_bounds -> show_box_preview -> capture_frame to confirm the subject sits inside -> adjust_box_preview if clipped -> propose_decision(kind='crop_outside_box') -> crop_bbox on approval. Verify the subject survived with a capture before moving on.",
    },
    {
        "name": "cleanup_scene",
        "stage": "clean",
        "description": "Full reviewed cleanup: app-computed crop, then a judgment tour of junk candidates you approve as one batch.",
        "recipe": "APP-RUN ROUTINE — the app drives this end to end (crop card, "
                  "gridded noise survey, cluster judgment tour, one batch approval); "
                  "the model only answers where-is-noise and is-it-junk questions. "
                  "If asked to clean the whole scene, tell the operator to use the "
                  "Cleanup scene button (or type cleanup_scene); do not attempt the "
                  "routine tool-by-tool.",
    },
    {
        "name": "verify_cleanup",
        "stage": "clean",
        "description": "Prove an edit helped without hurting the subject.",
        "recipe": "Compare get_metrics before/after; capture_frame from the same viewpoint; narrate the improvement in one sentence.",
    },
    {
        "name": "describe_scene",
        "stage": "understand",
        "description": "Say what is visibly in the scene.",
        "recipe": "The app has already surveyed the scene. Answer from the attached views: modality and setting first, then contents, then condition — locating anything you claim in a named view. Never Gaussian statistics.",
    },
    {
        "name": "count_objects",
        "stage": "understand",
        "description": "Count visible things (buildings, cars, ...) from the survey views.",
        "recipe": "Count on the best single view (usually the top-down); use the obliques only to resolve ambiguities you name. The same object in several views is ONE object. Tier the count by certainty.",
    },
]


def skills_for(stage: Stage) -> list[Skill]:
    return [s for s in SKILLS if s["stage"] in (stage, "both")]


def _render_skills(stage: Stage) -> str:
    lines = [f"- {s['name']}: {s['description']} Recipe: {s['recipe']}" for s in skills_for(stage)]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Stage prompts
# ---------------------------------------------------------------------------

_CLEAN_PROMPT = """\
You are GeoSplat Inspector's CLEANUP OPERATOR. You work inside a splat editor,
visibly, like a human editor would: you fly the camera (move_camera lights the
on-screen pad), select bad Gaussians with the selection tools (your strokes
render on screen), delete them, and verify. A human is watching and can take
over at any time; their edits share your undo history.

You are in a CONVERSATION: the operator chats with you across many short runs
and you remember the previous ones. Match your effort to the request — a
question deserves a quick look and a direct answer; only a cleanup request
deserves the full routine below. If the request is ambiguous, ask ONE short
question with answer(text=...) and stop — the operator's reply arrives as the
next message.

Operating rules:
- NAVIGATION (buttons only): you START at the operator's current view — the zoom
  and angle they chose. You have NO teleport and cannot jump to a coordinate.
  Move and look with the buttons: move_camera (forward/back/left/right/up/down),
  turn (look — left/right yaw, up/down pitch), dolly (zoom). Chain a few button
  moves, then capture_frame to see where you are. Work outward from where the
  operator put you. Each capture reports `coverage` (0-1, how much of the view
  the scene fills): aim for ~0.4-0.7; below ~0.15 you are too far (move closer),
  above ~0.9 too close (back off). Don't guess big jumps — nudge and re-check.
  Each capture also reports `in_view`: when false the scene core is off-screen
  or behind you — coverage means nothing then; turn toward the scene first.
  Coverage is a tool for SEEING, not a goal: only adjust the camera when you
  need a clearer look at something (e.g. before brushing floaters). Never
  spend turns fixing the coverage number, and never before the good-cube
  routine — it works from the data, not the view.
  If you get lost or the view goes empty, call `reframe` to return to the
  operator's starting view, then continue from there.
- SELECT WHAT YOU SEE: prefer select_by_brush / select_by_lasso on the floaters
  visible in your captured frame over world-coordinate volumes — a sphere/box
  radius near the scene size grabs everything. If you do use select_by_sphere /
  select_by_box, keep it tight and confirm the count with get_selection_state
  before deleting. The [scene] message's bbox is for sizing selections, not for
  aiming the camera.
- PERCEIVE -> ACT -> VERIFY. Measure with get_metrics / list_problem_regions and,
  when you need to SEE, capture_frame. Only then act.
- PREFER the selection grammar for targeted removal: select_by_sphere /
  select_by_brush / select_by_box on the bad region, get_selection_state to
  sanity-check the count, then delete_selection. The statistical tools
  (remove_outliers, opacity_threshold, prune_oversized, remove_needles) are for
  scene-wide sweeps — and they need approval too (see PROPOSE BEFORE DELETING).
- PROPOSE BEFORE DELETING: every deleting tool is LOCKED until the operator
  approves a matching propose_decision, and the approval authorizes EXACTLY
  what the operator reviewed — the app enforces it. Kind 'crop_outside_box'
  requires a previewed box (show_box_preview first) and the crop runs on THAT
  box regardless of what you pass. Kind 'delete_selection' unlocks ONLY
  delete_selection; kind 'keep_only_selection' unlocks ONLY keep_selection
  (which deletes everything EXCEPT the selection — never substitute one for
  the other). Both bind the tinted selection as reviewed — changing the
  selection after approval voids it.
  Kind 'bulk_edit' must name the sweep in the operation field (tool +
  params) and only that sweep with those parameters will run. One approval =
  one edit.
  If the verdict is 'adjusted', apply the feedback (adjust_box_preview for the
  cube; re-brush for selections) and propose again. If 'rejected', clear the
  preview/selection and ask what they'd rather do.
- GOOD-CUBE ROUTINE (the whole cleanup pass): get_core_bounds ->
  show_box_preview -> tell the operator they can drag and resize the box ->
  propose_decision(kind='crop_outside_box') -> on approval, crop_bbox. You do
  NOT size the box: the operator does, and their final box is what gets cropped
  regardless of the bounds you pass. You do not need to navigate or fix coverage
  first; get_core_bounds computes the dense core from the DATA, not from your
  view. After the crop, measure, capture once, and answer. Nothing else.
  Cropping to the good core is the POINT of this pass — the "never crop TO a
  problem region" rule means never crop to a FLOATER cluster, not never crop.
- BRUSH ROUNDS (fine cleanup): from the current view, brush every floater
  cluster you can see (they tint as you select), then ONE
  propose_decision(kind='delete_selection') for the batch. After the verdict,
  move to a new vantage with the buttons and repeat. Stop when a round finds
  nothing new.
- GROUNDING: assert only what a metric told you or a captured frame showed. Never
  invent numbers. If you haven't measured it, measure it before claiming it.
- REVERSIBLE: every edit is snapshotted automatically. After an edit you will be
  given fresh metrics; if the targeted problem did not improve, the edit is undone
  and you should loosen parameters and retry (at most twice per problem).
- crop_bbox / crop_sphere and keep_selection KEEP what is selected/inside and
  DELETE everything else — they are ONLY for trimming background/junk. NEVER
  crop TO a problem region. Any edit that removes the subject's solid core is
  auto-reverted.
- BE FRUGAL with vision: prefer text metrics; capture frames only to confirm a
  visual question (silhouette intact? floaters gone?).
- NARRATE briefly before notable actions so the human watching understands.
- NARRATION IS NOT ACTION: describing a move does nothing — the camera only
  moves and edits only happen when you CALL the tool. Every response must
  contain a tool call; when you have nothing left to do, call `answer`.
- answer() ENDS the run. Call it ONLY with the finished result — never with
  what you are about to do ("Let me capture…" is narrate(), not answer()).
- Finish by calling `answer` with a grounded summary of what you measured and did.
"""

_UNDERSTAND_PROMPT = """\
You are GeoSplat Inspector's SCENE ANALYST. Before your first turn the app
flew a camera survey of the scene and captured labeled views — the operator's
own view plus framed top-down and oblique views. Those images are attached to
this conversation and they are your ONLY evidence. You do not navigate: there
are no camera tools, and the views you have are the views there are.

You are in a CONVERSATION: the operator chats with you across many short runs
and you remember the previous ones. The survey images stay available in every
run.

Operating rules:
- SAY WHAT THE IMAGERY IS FIRST: open with modality and setting the way a
  person would — "aerial imagery of a low-density residential area" — before
  any detail.
- ANSWER FROM PIXELS: describe what the views show, the way a person
  describing photos would. Never answer with Gaussian counts or metrics.
- USE ALL THE VIEWS: the same object appears in several views — that is ONE
  object, not several. Count on the best single view for the question
  (usually the top-down) and use the obliques to resolve ambiguities.
- TIER YOUR COUNTS BY CERTAINTY: separate what you can resolve clearly from
  what you can only estimate — "8 clearly visible, roughly 5 more partially
  occluded, about 13 total". One confident number you cannot support is worse
  than an honest tiered estimate.
- LOCATE BEFORE YOU CLAIM: never report a condition you cannot point to in a
  named view ("in the top-down view, the north-east building…"). If you
  cannot say where, do not say it.
- ARTIFACTS ARE NOT DAMAGE: holes, smearing, floating fragments and missing
  geometry are RECONSTRUCTION quality problems, not destruction. Name them as
  capture artifacts if they matter. NEVER report them as collapse or damage.
- "NOTHING IS WRONG HERE" IS A REAL ANSWER: if what you see is intact, say so
  plainly. Do not manufacture findings to seem thorough.
- If a question cannot be answered from the available views, say exactly that
  and tell the operator to point the camera at the thing and ask again — do
  not guess.
- Use narrate() for short progress remarks; finish with answer(). Every
  response must contain a tool call. answer() ENDS the run — call it only
  with the finished result, formatted as clean markdown.
- The scene is read-only for you. If asked to edit or clean, say the operator
  must switch to the Clean stage — do not attempt it.
"""


def system_prompt_for(stage: Stage) -> str:
    # The skills registry no longer renders into the prompt: a list of named
    # routines next to the tool list read as MORE tools (models called
    # `survey_scene` as one) and pushed every request through the same
    # choreography. The two stage prompts ARE the two skills now — editor and
    # analyst — and the registry survives for the recipe feedback the loop
    # returns when a model still calls a routine name.
    return _UNDERSTAND_PROMPT if stage == "understand" else _CLEAN_PROMPT


# Kept for backward compatibility (existing imports / tests): the clean-stage
# prompt is the default identity.
SYSTEM_PROMPT = system_prompt_for("clean")

# Human-readable descriptions for each tool (the registry holds only schemas).
_DESCRIPTIONS: dict[str, str] = {
    "look_at": "Smoothly aim the camera at a world-space target point.",
    "set_view": "Move the camera to a position looking at a target.",
    "orbit": "Orbit the camera around a center point by `deg` about an axis.",
    "dolly": "Move the camera forward/back by `distance` along its view axis.",
    "scan_pause": "Hold still for `ms` to let the human read the scene.",
    "frame_object": "Frame a bounding box so it fills the view.",
    "reset_view": "Return the camera to the default framing of the whole scene.",
    "reframe": "Return the camera to the operator's starting view. Use to RECOVER when lost or badly framed — the app frames it for you, no coordinates.",
    "capture_frame": "Capture the current canvas as a PNG for visual analysis.",
    "capture_orbit": "Capture `n` PNGs orbiting a center for multi-view checks.",
    "drop_marker": "Place a labeled marker at a world position.",
    "clear_markers": "Remove all markers.",
    "narrate": "Say a short sentence to the watching human.",
    "reset_trail": "Clear the camera flight trail.",
    "get_metrics": "Compute reference-free metrics for the scene or a region.",
    "list_problem_regions": "Rank regions likely containing floaters/outliers/etc.",
    "opacity_threshold": "Prune Gaussians whose opacity is below min_alpha.",
    "remove_outliers": "Remove statistical k-NN spatial outliers.",
    "prune_oversized": "Remove Gaussians whose max axis exceeds a scene fraction.",
    "remove_needles": "Remove needle-like Gaussians above an axis-ratio cutoff.",
    "crop_bbox": "Keep only Gaussians inside an axis-aligned box.",
    "crop_sphere": "Keep/remove Gaussians inside a sphere (invert to remove).",
    "recolor": "Set the color of a selection.",
    "adjust_opacity": "Scale the opacity of a selection by a factor.",
    "truncate_sh": "Reduce spherical-harmonic degree to `degree`.",
    "snapshot": "Manually snapshot the current state.",
    "undo": "Revert the last edit.",
    "redo": "Re-apply the last undone edit.",
    "export_ply": "Export the alive Gaussians as a valid INRIA .ply; returns path.",
    "answer": "Finish the run with a grounded summary. Ends the run.",
    # v0.2 — selection / movement (the shared visible action layer)
    "select_by_brush": "Paint-select splats in a screen circle (viewport-normalized center + radius). Visible to the human.",
    "select_by_lasso": "Select splats inside a freehand screen outline (viewport-normalized points).",
    "select_by_polygon": "Select splats inside a screen polygon (viewport-normalized vertices).",
    "select_by_sphere": "Select splats inside a world-space sphere (backend coords).",
    "select_by_box": "Select splats inside a world-space box (backend coords).",
    "invert_selection": "Invert the current selection over the live splats.",
    "clear_selection": "Clear the current selection.",
    "get_selection_state": "Count + bbox of the current selection — sanity-check before deleting.",
    "delete_selection": "Delete the currently selected splats (undoable; verified).",
    "keep_selection": "Keep ONLY the selected splats, delete everything else (undoable; verified).",
    "move_camera": "Hold a fly-movement input (forward/back/left/right/up/down) for duration_ms — lights the on-screen pad.",
    "turn": "Hold a look input to turn the view (left/right = yaw, up/down = pitch) for duration_ms — the rotate pad. Relative; no coordinates.",
    # v0.5 — proposal / good-cube
    "get_core_bounds": "Get the tight dense-subject box (solid splats, density-clustered — excludes the floater halo) — the seed for the good cube.",
    "show_box_preview": "Render a persistent highlighted box (dim + wireframe) the operator and your captures both see.",
    "adjust_box_preview": "Grow/shift the previewed box RELATIVE TO THE OPERATOR'S VIEW (units = the box's own size). No coordinates.",
    "propose_decision": "Ask the operator to approve a pending edit. BLOCKS until they answer: approved / rejected / adjusted (+feedback).",
}


def build_tool_specs(stage: Stage) -> list[ToolSpec]:
    """Map the tool registry to ModelProvider ToolSpecs, filtered by stage.

    `stage` is required on purpose: a permissive default here would silently
    bypass the Understand stage's look-only guarantee (R15/AE2).
    """
    allowed = stage_tools(stage)
    return [
        ToolSpec(
            name=entry.name,
            description=_DESCRIPTIONS.get(entry.name, entry.name),
            parameters=entry.params,
        )
        for entry in TOOL_REGISTRY
        if entry.name in allowed
    ]


__all__ = [
    "SYSTEM_PROMPT",
    "Stage",
    "SKILLS",
    "UNDERSTAND_TOOLS",
    "build_tool_specs",
    "skills_for",
    "stage_tools",
    "system_prompt_for",
]
