"""Scene-hull carve for the cleanup run (v0.8.1, scene-hull lock-on).

The operator's framing, made mechanical: a human looks at the scene, sees
where the ACTUAL scene is, and everything else is junk by contrast. The model
does the seeing — one `outline_scene` box per survey view (figure/ground, the
easy question) — and this module does the geometry: a splat center is vouched
for when it reprojects inside the outlined box in enough of the views that can
see it. The result intersects the statistical subject (the safety floor), so
reasoning leads and statistics bound the damage of a bad outline.
"""
from __future__ import annotations

import numpy as np

from backend.analysis.clusters import project_uv
from backend.analysis.subject import SubjectLevels

# Per-level box padding in normalized image units, tight -> loose. Negative
# pads shrink the model's outline (stricter than its own box); positive pads
# forgive outline slop. Must ascend so the levels stay nested.
DEFAULT_PADS: tuple[float, ...] = (-0.05, -0.02, 0.0, 0.05, 0.12)


def apply_hull(
    subject: SubjectLevels,
    means: np.ndarray,
    ids: np.ndarray,
    views: list[dict],
    *,
    pads: tuple[float, ...] = DEFAULT_PADS,
    min_frac: float = 0.5,
    min_splats: int = 100,
) -> SubjectLevels:
    """Carve `subject` down to the splats the outlined views vouch for.

    `views` is a list of {"pose": <render-space pose>, "box": (x0,y0,x1,y1)}
    in normalized [0,1] image coordinates. A splat is kept at level k when it
    lands inside the (pad_k-expanded) box in >= min_frac of the views it is in
    front of; splats no view can see are junk by construction (the survey
    frames the scene). Falls back to `subject` unchanged when there are no
    usable views or the carve leaves fewer than `min_splats` at the default
    level (the outlines were unusable).
    """
    if not views:
        return subject
    means = np.asarray(means, dtype=np.float64)
    ids = np.asarray(ids)
    n = len(means)
    n_levels = len(subject.level_ids)
    lv_pads = sorted(pads)[:n_levels]
    while len(lv_pads) < n_levels:
        lv_pads.append(lv_pads[-1])

    visible = np.zeros(n, dtype=np.int64)
    inside = np.zeros((n_levels, n), dtype=np.int64)
    for view in views:
        u, v, in_front = project_uv(means, view["pose"])
        x0, y0, x1, y1 = view["box"]
        visible += in_front
        for k, pad in enumerate(lv_pads):
            ok = (
                in_front
                & (u >= x0 - pad) & (u <= x1 + pad)
                & (v >= y0 - pad) & (v <= y1 + pad)
            )
            inside[k] += ok

    need = np.maximum(1, np.ceil(visible * min_frac).astype(np.int64))
    level_ids: list[np.ndarray] = []
    for k in range(n_levels):
        vouched = ids[(visible > 0) & (inside[k] >= need)]
        level_ids.append(np.intersect1d(subject.level_ids[k], vouched))

    default = subject.default_level
    if len(level_ids[default]) < min_splats:
        return subject               # unusable outlines — the floor stands

    pos_of = {int(i): r for r, i in enumerate(ids)}
    rows = np.asarray([pos_of[int(i)] for i in level_ids[default]], dtype=np.int64)
    p = means[rows]
    return SubjectLevels(
        level_ids=level_ids,
        counts=[int(len(l)) for l in level_ids],
        default_level=default,
        bbox_min=[float(x) for x in p.min(axis=0)],
        bbox_max=[float(x) for x in p.max(axis=0)],
    )


__all__ = ["DEFAULT_PADS", "apply_hull"]
