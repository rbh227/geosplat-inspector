"""End-to-end REST acceptance: upload -> metrics -> edit -> fetch edited .ply,
plus undo/redo — exercised on the real example scene."""

from __future__ import annotations

import io
import os

import pytest
from fastapi.testclient import TestClient

from backend.server import create_app

EXAMPLES = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "examples",
)
MESSY = os.path.join(EXAMPLES, "messy.ply")


def _ply_vertex_count(data: bytes) -> int:
    end = data.index(b"end_header")
    header = data[:end].decode("ascii")
    for line in header.splitlines():
        if line.startswith("element vertex"):
            return int(line.split()[-1])
    raise AssertionError("no vertex count")


@pytest.fixture
def client():
    return TestClient(create_app())


def test_upload_returns_count_without_computing_metrics(client, monkeypatch):
    """Upload must not run k-NN metrics — it freezes the viewer for minutes on
    a large scene, and nothing in the upload path needs them.

    Enforced by sabotage: metrics() raises, so any call from the upload path
    fails the test rather than merely slowing it down."""
    from backend.api.real_engine import RealScene
    from backend.api.stub_engine import StubScene

    def _boom(self, *a, **kw):
        raise AssertionError("upload computed metrics — it must not")

    # Whichever engine create_app() selected (real, stub fallback) is sabotaged.
    monkeypatch.setattr(RealScene, "metrics", _boom)
    monkeypatch.setattr(StubScene, "metrics", _boom)

    with open(MESSY, "rb") as f:
        resp = client.post("/scene", files={"file": ("messy.ply", f, "application/octet-stream")})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] > 0
    assert "metrics" not in body, "upload must not carry metrics"


def test_upload_metrics_edit_fetch_roundtrip(client):
    assert os.path.exists(MESSY), "examples/messy.ply (Phase 0) is required"

    # 1. upload -> id + count (metrics are computed on demand, not here)
    with open(MESSY, "rb") as f:
        resp = client.post("/scene", files={"file": ("messy.ply", f, "application/octet-stream")})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    scene_id = body["id"]
    assert body["count"] > 0

    # 2. metrics endpoint computes them on demand
    r = client.get("/metrics", params={"scene_id": scene_id})
    assert r.status_code == 200
    m0 = r.json()
    assert m0["gaussianCount"] == body["count"]
    # frozen Metrics schema is structurally complete
    for key in ("opacity", "scale", "spatial", "bounds", "color", "computedAt"):
        assert key in m0
    assert "needleFraction" in m0["scale"]["axisRatio"]

    # 3. fetch original .ply (serving reflects current alive set)
    r = client.get(f"/scene/{scene_id}.ply")
    assert r.status_code == 200
    n_before = _ply_vertex_count(r.content)
    assert n_before == m0["gaussianCount"]

    # 4. edit: prune floaters by opacity threshold -> fewer Gaussians
    r = client.post("/edit", json={
        "scene_id": scene_id,
        "op": "opacity_threshold",
        "params": {"min_alpha": 0.5},
    })
    assert r.status_code == 200, r.text
    edit = r.json()
    assert edit["before"] > edit["after"], "opacity prune should drop Gaussians"
    assert edit["metrics"]["gaussianCount"] == edit["after"]

    # 5. fetch edited .ply -> serving reflects the smaller alive set
    r = client.get(f"/scene/{scene_id}.ply")
    assert r.status_code == 200
    n_after = _ply_vertex_count(r.content)
    assert n_after == edit["after"] < n_before

    # edited file is a valid, loadable INRIA ply we can re-upload
    re = client.post("/scene", files={"file": ("edited.ply", io.BytesIO(r.content), "application/octet-stream")})
    assert re.status_code == 200
    assert re.json()["count"] == n_after


def test_undo_redo(client):
    with open(MESSY, "rb") as f:
        scene_id = client.post("/scene", files={"file": ("m.ply", f, "application/octet-stream")}).json()["id"]
    base = client.get("/metrics", params={"scene_id": scene_id}).json()["gaussianCount"]

    after = client.post("/edit", json={
        "scene_id": scene_id, "op": "crop_sphere",
        "params": {"center": [0, 0, 0], "radius": 1.5},
    }).json()["after"]
    assert after != base

    u = client.post("/undo", json={"scene_id": scene_id}).json()
    assert u["ok"] is True
    assert u["count"] == base

    rd = client.post("/redo", json={"scene_id": scene_id}).json()
    assert rd["ok"] is True
    assert rd["count"] == after


def test_unknown_scene_and_bad_op(client):
    assert client.get("/metrics", params={"scene_id": "nope"}).status_code == 404
    with open(MESSY, "rb") as f:
        sid = client.post("/scene", files={"file": ("m.ply", f, "application/octet-stream")}).json()["id"]
    bad = client.post("/edit", json={"scene_id": sid, "op": "does_not_exist", "params": {}})
    assert bad.status_code == 400
