#!/usr/bin/env python
"""Headless demo rehearsal: drive the RUNNING backend + LIVE model end to end.

Emulates the browser renderer over the real WebSocket protocol — projects the
actual splats to PNG for capture_frame, executes selection/camera tools on real
positions, and auto-APPROVES proposals like an operator would. Then runs the
demo script: a Clean-stage cleanup, an Understand-stage question, and a memory
follow-up. Exits non-zero if any run fails.

Usage:  .venv-api/bin/python scripts/e2e_live.py [path/to/scene.ply]
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import math
import sys
import time
import urllib.request

import numpy as np
import websockets
from PIL import Image, ImageDraw

sys.path.insert(0, ".")
from backend.splat import GaussianSplatModel  # noqa: E402

BASE = "http://localhost:8000"
W, H = 640, 400
FOV_Y = 60 * math.pi / 180


def http(method: str, path: str, body: dict | None = None, timeout: float = 300):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def upload(path: str) -> str:
    boundary = "e2eboundary"
    with open(path, "rb") as f:
        blob = f.read()
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"scene.ply\"\r\nContent-Type: application/octet-stream\r\n\r\n"
    ).encode() + blob + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        BASE + "/scene", data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)["id"]


class FakeRenderer:
    """The browser's job, headless: real projection, real selection geometry."""

    def __init__(self, model: GaussianSplatModel, scene_id: str):
        self.scene_id = scene_id
        self.model = model
        self.refresh_alive()
        mn, mx = model.bounds()
        self.center = (mn + mx) / 2
        self.radius = float(np.linalg.norm(mx - mn) / 2) or 1.0
        self.home()
        self.selection: set[int] = set()   # original ids
        self.preview_box: dict | None = None
        self.proposals: list[dict] = []
        self.captures = 0

    # -- state ------------------------------------------------------------
    def refresh_alive(self) -> None:
        ids = http("GET", f"/ids?scene_id={self.scene_id}")["ids"]
        self.alive_ids = np.array(ids, dtype=np.int64)
        self.pos = self.model.means[self.alive_ids]
        self.rgb = np.clip(0.5 + 0.28209479 * self.model.f_dc[self.alive_ids], 0, 1)
        self.opa = 1 / (1 + np.exp(-self.model.opacity_raw[self.alive_ids]))

    def home(self) -> None:
        self.cam = self.center + np.array([0.0, 0.6, 1.0]) * self.radius * 2.0
        d = self.center - self.cam
        self.yaw = math.atan2(d[0], -d[2])
        self.pitch = math.asin(d[1] / (np.linalg.norm(d) or 1))

    def basis(self):
        cy, sy, cp, sp = math.cos(self.yaw), math.sin(self.yaw), math.cos(self.pitch), math.sin(self.pitch)
        fwd = np.array([sy * cp, sp, -cy * cp])
        right = np.array([cy, 0, sy])
        up = np.cross(right, fwd)
        return fwd, right, up

    # -- rendering --------------------------------------------------------
    def project(self, pts: np.ndarray):
        fwd, right, up = self.basis()
        rel = pts - self.cam
        z = rel @ fwd
        x = rel @ right
        y = rel @ up
        f = (H / 2) / math.tan(FOV_Y / 2)
        with np.errstate(divide="ignore", invalid="ignore"):
            u = W / 2 + f * x / np.maximum(z, 1e-6)
            v = H / 2 - f * y / np.maximum(z, 1e-6)
        return u, v, z

    def render(self) -> bytes:
        img = Image.new("RGB", (W, H), (8, 8, 12))
        draw = ImageDraw.Draw(img)
        u, v, z = self.project(self.pos)
        order = np.argsort(-z)
        for i in order:
            if z[i] <= 0 or not (0 <= u[i] < W and 0 <= v[i] < H):
                continue
            c = tuple(int(255 * ch) for ch in self.rgb[i])
            if self.alive_ids[i] in self.selection:
                c = (255, 120, 40)
            r = max(1, int(3 * self.radius / max(z[i], 1e-3) * 0.05))
            draw.ellipse([u[i] - r, v[i] - r, u[i] + r, v[i] + r], fill=c)
        if self.preview_box:
            bs = self.box_screen()
            if bs:
                draw.rectangle([bs["u0"] * W, bs["v0"] * H, bs["u1"] * W, bs["v1"] * H],
                               outline=(80, 220, 255), width=2)
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()

    def box_screen(self) -> dict | None:
        if not self.preview_box:
            return None
        mn, mx = np.array(self.preview_box["min"]), np.array(self.preview_box["max"])
        corners = np.array([[mn[0], mn[1], mn[2]], [mx[0], mn[1], mn[2]],
                            [mn[0], mx[1], mn[2]], [mn[0], mn[1], mx[2]],
                            [mx[0], mx[1], mn[2]], [mx[0], mn[1], mx[2]],
                            [mn[0], mx[1], mx[2]], [mx[0], mx[1], mx[2]]])
        u, v, z = self.project(corners)
        if (z <= 0).all():
            return None
        return {"u0": float(u.min() / W), "v0": float(v.min() / H),
                "u1": float(u.max() / W), "v1": float(v.max() / H)}

    def percept(self) -> dict:
        u, v, z = self.project(self.pos)
        vis = (z > 0) & (u >= 0) & (u < W) & (v >= 0) & (v < H)
        cov = 0.0
        if vis.any():
            span_u = (u[vis].max() - u[vis].min()) / W
            span_v = (v[vis].max() - v[vis].min()) / H
            cov = round(float(min(1.0, span_u * span_v * (vis.mean() * 4))), 2)
        fwd, _, _ = self.basis()
        rel = self.center - self.cam
        in_view = bool(rel @ fwd > 0)
        p = {"position": [round(float(x), 2) for x in self.cam],
             "target": [round(float(x), 2) for x in self.center],
             "revision": 0, "coverage": cov, "in_view": in_view}
        bs = self.box_screen()
        if bs:
            p["box_screen"] = bs
        return p

    # -- command handling ---------------------------------------------------
    def handle(self, ctype: str, payload: dict) -> dict:
        tool = payload.get("tool", "")
        args = payload.get("args", {}) or {}
        step = self.radius * 0.15

        if ctype == "capture_request":
            self.captures += 1
            if tool == "capture_orbit":
                n = int(args.get("n", 4))
                frames = []
                for k in range(n):
                    self.yaw += 2 * math.pi / n
                    frames.append(base64.b64encode(self.render()).decode())
                return {"ok": True, "frames_base64": frames}
            return {"ok": True, "png_base64": base64.b64encode(self.render()).decode(),
                    "percept": self.percept()}

        if ctype == "movement_input":
            fwd, right, up = self.basis()
            d = {"forward": fwd, "back": -fwd, "left": -right, "right": right,
                 "up": up, "down": -up}.get(args.get("direction", "forward"), fwd)
            self.cam = self.cam + d * step * (args.get("duration_ms", 500) / 500)
            return {"ok": True}

        if ctype == "rotation_input":
            amt = 0.5 * (args.get("duration_ms", 500) / 500)
            d = args.get("direction", "left")
            if d == "left":
                self.yaw -= amt
            elif d == "right":
                self.yaw += amt
            elif d == "up":
                self.pitch = min(1.4, self.pitch + amt)
            else:
                self.pitch = max(-1.4, self.pitch - amt)
            return {"ok": True}

        if ctype == "camera_move":
            if tool == "dolly":
                fwd, _, _ = self.basis()
                self.cam = self.cam + fwd * float(args.get("distance", 1))
            elif tool in ("reset_view", "reframe"):
                self.home()
            elif tool in ("look_at", "frame_object", "set_view"):
                tgt = np.array(args.get("target", args.get("center", self.center)), dtype=float)[:3]
                d = tgt - self.cam
                self.yaw = math.atan2(d[0], -d[2])
                self.pitch = math.asin(float(d[1] / (np.linalg.norm(d) or 1)))
            return {"ok": True}

        if ctype == "selection_tool":
            return self.selection_tool(tool, args)

        if ctype == "get_selection":
            return {"ids": [int(i) for i in sorted(self.selection)]}

        if ctype == "proposal":
            self.proposals.append(dict(args))
            print(f"    [operator] proposal kind={args.get('kind')!r}: "
                  f"{str(args.get('summary'))[:100]} -> APPROVED")
            return {"ok": True, "verdict": "approved"}

        if ctype in ("narrate", "drop_marker", "clear_markers", "box_preview"):
            return {"ok": True}
        return {"ok": True}

    def selection_tool(self, tool: str, args: dict) -> dict:
        def sel_result():
            n = len(self.selection)
            if n == 0:
                return {"ok": True, "count": 0, "bbox": None}
            pts = self.model.means[np.array(sorted(self.selection), dtype=np.int64)]
            return {"ok": True, "count": n,
                    "bbox": {"min": pts.min(axis=0).tolist(), "max": pts.max(axis=0).tolist()}}

        mode = args.get("mode", "add")

        def apply(ids: np.ndarray):
            chosen = set(int(i) for i in self.alive_ids[ids])
            if mode == "remove":
                self.selection -= chosen
            else:
                self.selection |= chosen

        if tool == "select_by_sphere":
            c = np.array(args["center"], dtype=float)[:3]
            r = float(args["radius"])
            apply(np.where(np.linalg.norm(self.pos - c, axis=1) <= r)[0])
            return sel_result()
        if tool == "select_by_box":
            mn = np.array(args["min"], dtype=float)[:3]
            mx = np.array(args["max"], dtype=float)[:3]
            apply(np.where(((self.pos >= mn) & (self.pos <= mx)).all(axis=1))[0])
            return sel_result()
        if tool in ("select_by_brush", "select_by_lasso", "select_by_polygon"):
            u, v, z = self.project(self.pos)
            un, vn = u / W, v / H
            if tool == "select_by_brush":
                cu, cv = args["center_xy"]
                r = float(args["radius"])
                hit = (z > 0) & (np.hypot(un - cu, (vn - cv) * (H / W) * (W / H)) <= r)
            else:
                pts = np.array(args["points_xy"], dtype=float)
                cu, cv = pts[:, 0].mean(), pts[:, 1].mean()
                r = max(pts[:, 0].ptp(), pts[:, 1].ptp()) / 2 or 0.05
                hit = (z > 0) & (np.hypot(un - cu, vn - cv) <= r)
            apply(np.where(hit)[0])
            return sel_result()
        if tool == "invert_selection":
            self.selection = set(int(i) for i in self.alive_ids) - self.selection
            return sel_result()
        if tool == "clear_selection":
            self.selection = set()
            return {"ok": True, "count": 0}
        if tool == "get_selection_state":
            return sel_result()
        if tool == "get_core_bounds":
            solid = self.pos[self.opa >= 0.3] if (self.opa >= 0.3).sum() >= 8 else self.pos
            mn = np.percentile(solid, 2, axis=0)
            mx = np.percentile(solid, 98, axis=0)
            inside = int((((self.pos >= mn) & (self.pos <= mx)).all(axis=1)).sum())
            return {"ok": True, "min": mn.tolist(), "max": mx.tolist(), "count": inside}
        if tool == "show_box_preview":
            self.preview_box = {"min": args["min"], "max": args["max"]}
            return {"ok": True, **self.preview_box}
        if tool == "adjust_box_preview":
            if not self.preview_box:
                return {"ok": False, "error": "no preview box"}
            mn = np.array(self.preview_box["min"], dtype=float)
            mx = np.array(self.preview_box["max"], dtype=float)
            c, half = (mn + mx) / 2, (mx - mn) / 2
            g = float(args.get("grow", 1.0) or 1.0)
            half = half * g
            ga = args.get("grow_axes")
            if ga:
                half = half * np.array(ga, dtype=float)[:3]
            sh = args.get("shift")
            if sh:
                fwd, right, up = self.basis()
                world = (right * sh[0] + up * sh[1] + fwd * sh[2]) * (2 * half)
                c = c + world
            self.preview_box = {"min": (c - half).tolist(), "max": (c + half).tolist()}
            return {"ok": True, **self.preview_box}
        return {"ok": False, "error": f"unhandled selection tool {tool}"}


async def run_prompt(ws, renderer: FakeRenderer, scene_id: str, prompt: str, stage: str):
    print(f"\n== [{stage}] {prompt!r}")
    t0 = time.time()
    done = asyncio.Event()
    outcome: dict = {}
    tool_seq: list[str] = []

    async def pump():
        async for raw in ws:
            msg = json.loads(raw)
            mtype = msg.get("type")
            payload = msg.get("payload", {})
            # Commands carry a correlation id and MUST be replied to (narrate
            # included — the dispatcher awaits it); loop trace events never do.
            if "id" in msg:
                reply = renderer.handle(mtype, payload)
                await ws.send(json.dumps({"type": "frame", "id": msg["id"], "payload": reply}))
                continue
            if mtype == "tool_call":
                tool_seq.append(payload.get("name", "?"))
                print(f"    -> {payload.get('name')} {json.dumps(payload.get('args', {}))[:90]}")
            elif mtype == "thought":
                print(f"    [thought] {str(payload.get('text'))[:110]}")
            elif mtype == "narrate":
                print(f"    [narrate] {str(payload.get('text'))[:110]}")
            elif mtype == "tool_result":
                name = payload.get("name", "")
                if str(name).startswith("verify:") or name in ("undo",):
                    print(f"    [verify] {str(payload.get('result'))[:110]}")
            elif mtype == "complete":
                outcome.update(payload)
                done.set()
                return

    pumper = asyncio.create_task(pump())
    http("POST", "/agent/run", {"scene_id": scene_id, "prompt": prompt, "stage": stage})
    try:
        await asyncio.wait_for(done.wait(), timeout=600)
    finally:
        pumper.cancel()
    dt = time.time() - t0
    status = outcome.get("status")
    print(f"  == complete in {dt:.0f}s: status={status!r} scene_changed={outcome.get('scene_changed')}")
    if outcome.get("answer"):
        print(f"  answer: {outcome['answer'][:300]}")
    if outcome.get("error"):
        print(f"  ERROR: {outcome['error'][:300]}")
    if outcome.get("scene_changed"):
        renderer.refresh_alive()
        renderer.selection = set()
        renderer.preview_box = None
    return {"status": status, "error": outcome.get("error"), "tools": tool_seq,
            "scene_changed": outcome.get("scene_changed"), "seconds": dt}


async def main():
    ply = sys.argv[1] if len(sys.argv) > 1 else "examples/messy.ply"
    print(f"scene: {ply}")
    scene_id = upload(ply)
    model = GaussianSplatModel.load(ply)
    count0 = http("GET", f"/metrics?scene_id={scene_id}")["gaussianCount"]
    print(f"scene {scene_id}: {count0} gaussians")

    results = []
    async with websockets.connect(f"ws://localhost:8000/ws/{scene_id}", max_size=2**24) as ws:
        renderer = FakeRenderer(model, scene_id)
        results.append(await run_prompt(ws, renderer, scene_id,
                                        "Clean up this scene: remove the floaters and junk around the main object.",
                                        "clean"))
        results.append(await run_prompt(ws, renderer, scene_id,
                                        "What shape is the main object in this scene?",
                                        "understand"))
        results.append(await run_prompt(ws, renderer, scene_id,
                                        "Summarize what you have done and seen in this scene so far.",
                                        "understand"))

    count1 = http("GET", f"/metrics?scene_id={scene_id}")["gaussianCount"]
    print(f"\n==== SUMMARY ====\ngaussians: {count0} -> {count1}")
    ok = True
    for i, r in enumerate(results):
        line = f"run {i + 1}: {r['status']} in {r['seconds']:.0f}s, {len(r['tools'])} tool calls"
        if r["error"]:
            line += f" ERROR={r['error'][:120]}"
        print(line)
        if r["status"] not in ("answered",) or r["error"]:
            ok = False
    if count1 >= count0:
        print("FAIL: cleanup removed nothing")
        ok = False
    edits = [t for r in results for t in r["tools"]
             if t in ("crop_bbox", "delete_selection", "opacity_threshold",
                      "remove_outliers", "prune_oversized", "remove_needles", "keep_selection")]
    print(f"destructive edits executed: {edits}")
    print("RESULT:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


asyncio.run(main())
