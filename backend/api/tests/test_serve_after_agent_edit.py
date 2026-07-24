"""Serving must reflect agent edits, not just `/edit`-route edits.

The agent edits the scene through the tool dispatcher, which never touches the
API routes — so `mark_dirty()` was never called for an agent run and
`GET /scene/{id}.ply` handed back the *original* upload. The frontend reloads
that URL after any run that reports `scene_changed`, so an approved crop was
silently undone on screen while the backend held the cropped model.

Staleness is therefore derived from the scene's alive count rather than from a
flag every edit path has to remember to set.
"""

from __future__ import annotations

import os

from backend.api.state import SceneState


class _CountingScene:
    """Minimal Scene stand-in whose alive count can be changed directly,
    simulating an edit that bypassed the API routes (i.e. the agent path)."""

    def __init__(self, count: int) -> None:
        self._count = count
        self.exports = 0

    def count(self) -> int:
        return self._count

    def export(self, path: str) -> None:
        self.exports += 1
        with open(path, "w") as fh:
            fh.write(f"alive={self._count}\n")

    # unused by these tests
    def metrics(self, region=None):
        return {"gaussianCount": self._count}


def _state(tmp_path, count: int = 2_000_000) -> tuple[SceneState, _CountingScene, str]:
    source = tmp_path / "source.ply"
    source.write_text("original\n")
    scene = _CountingScene(count)
    return SceneState("abc123", scene, str(source)), scene, str(source)


def test_unedited_scene_serves_the_source_file(tmp_path):
    state, scene, source = _state(tmp_path)
    assert state.current_ply_path() == source
    assert scene.exports == 0


def test_agent_edit_without_mark_dirty_is_served(tmp_path):
    """The regression: a crop applied through the dispatcher (no mark_dirty)."""
    state, scene, source = _state(tmp_path)
    assert state.current_ply_path() == source  # before the crop

    scene._count = 376_330  # the agent's approved crop lands on the model

    served = state.current_ply_path()
    assert served != source, "served the original upload after an agent edit"
    assert scene.exports == 1
    assert open(served).read().strip() == "alive=376330"


def test_route_edit_still_served(tmp_path):
    """The `/edit` path (which does call mark_dirty) keeps working."""
    state, scene, source = _state(tmp_path)
    scene._count = 1_999_000
    state.mark_dirty()
    served = state.current_ply_path()
    assert served != source
    assert open(served).read().strip() == "alive=1999000"


def test_export_is_cached_between_identical_serves(tmp_path):
    state, scene, _ = _state(tmp_path)
    scene._count = 100
    first = state.current_ply_path()
    second = state.current_ply_path()
    assert first == second
    assert scene.exports == 1, "re-exported despite no change"


def test_further_edit_triggers_re_export(tmp_path):
    state, scene, _ = _state(tmp_path)
    scene._count = 100
    state.current_ply_path()
    scene._count = 50
    path = state.current_ply_path()
    assert scene.exports == 2
    assert open(path).read().strip() == "alive=50"


def test_undo_back_to_full_scene_serves_source_again(tmp_path):
    """Undo restores every Gaussian, so the original upload is correct again."""
    state, scene, source = _state(tmp_path)
    scene._count = 100
    state.current_ply_path()
    scene._count = 2_000_000
    assert state.current_ply_path() == source


def test_cleanup_removes_the_export(tmp_path):
    state, scene, _ = _state(tmp_path)
    scene._count = 100
    path = state.current_ply_path()
    assert os.path.exists(path)
    state.cleanup()
    assert not os.path.exists(path)
