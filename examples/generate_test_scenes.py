#!/usr/bin/env python3
"""Generate clean.ply and messy.ply test scenes in INRIA 3DGS format.

clean.ply: 1000 Gaussians arranged as a tidy sphere surface.
messy.ply: 1200 Gaussians — same sphere + 200 deliberate defects:
  - 80 floaters (near-zero opacity, scattered far away)
  - 60 outliers (isolated points far from any neighbor)
  - 60 needles (extreme axis ratio > 10:1)

Both are SH degree 3 (45 f_rest coeffs) = 59 properties per Gaussian.
Binary little-endian, INRIA header order:
  x,y,z, nx,ny,nz, f_dc_0..2, f_rest_0..44, opacity, scale_0..2, rot_0..3

All values stored in raw/log/logit space as the INRIA format requires.
"""

import struct
import math
import random
import os

random.seed(42)

SH_C0 = 0.28209479177387814
SH_REST = 45  # degree 3

def sigmoid_inv(p: float) -> float:
    """logit: inverse sigmoid."""
    p = max(1e-6, min(1 - 1e-6, p))
    return math.log(p / (1 - p))

def log_scale(s: float) -> float:
    return math.log(max(1e-8, s))

def dc_from_rgb(r: float, g: float, b: float) -> tuple[float, float, float]:
    """Inverse: f_dc = (rgb - 0.5) / C0"""
    return ((r - 0.5) / SH_C0, (g - 0.5) / SH_C0, (b - 0.5) / SH_C0)

def write_ply(path: str, gaussians: list[dict]):
    """Write a list of Gaussian dicts to INRIA binary .ply."""
    n = len(gaussians)
    header = (
        "ply\n"
        "format binary_little_endian 1.0\n"
        f"element vertex {n}\n"
        "property float x\n"
        "property float y\n"
        "property float z\n"
        "property float nx\n"
        "property float ny\n"
        "property float nz\n"
        "property float f_dc_0\n"
        "property float f_dc_1\n"
        "property float f_dc_2\n"
    )
    for i in range(SH_REST):
        header += f"property float f_rest_{i}\n"
    header += (
        "property float opacity\n"
        "property float scale_0\n"
        "property float scale_1\n"
        "property float scale_2\n"
        "property float rot_0\n"
        "property float rot_1\n"
        "property float rot_2\n"
        "property float rot_3\n"
        "end_header\n"
    )

    # 3 pos + 3 normal + 3 dc + 45 rest + 1 opacity + 3 scale + 4 rot = 62 floats
    fmt = "<" + "f" * 62

    with open(path, "wb") as f:
        f.write(header.encode("ascii"))
        for g in gaussians:
            values = (
                list(g["pos"])
                + list(g["normal"])
                + list(g["f_dc"])
                + list(g["f_rest"])
                + [g["opacity"]]
                + list(g["scale"])
                + list(g["rot"])
            )
            f.write(struct.pack(fmt, *values))

    print(f"Wrote {n} Gaussians to {path} ({os.path.getsize(path)} bytes)")

def make_sphere_gaussian(theta: float, phi: float, radius: float = 1.0,
                         base_color: tuple = (0.6, 0.8, 0.4)) -> dict:
    """Create one well-behaved Gaussian on a sphere surface."""
    x = radius * math.sin(theta) * math.cos(phi)
    y = radius * math.sin(theta) * math.sin(phi)
    z = radius * math.cos(theta)

    # Small uniform scale (log space)
    s = 0.02 + random.uniform(0, 0.01)
    scale = (log_scale(s), log_scale(s), log_scale(s))

    # High opacity (logit)
    opacity = sigmoid_inv(0.85 + random.uniform(0, 0.10))

    # Slight color variation
    r = max(0, min(1, base_color[0] + random.gauss(0, 0.05)))
    g = max(0, min(1, base_color[1] + random.gauss(0, 0.05)))
    b = max(0, min(1, base_color[2] + random.gauss(0, 0.05)))

    # Unit quaternion (w,x,y,z) — identity with small jitter
    rot = (1.0, random.gauss(0, 0.05), random.gauss(0, 0.05), random.gauss(0, 0.05))

    return {
        "pos": (x, y, z),
        "normal": (0.0, 0.0, 0.0),
        "f_dc": dc_from_rgb(r, g, b),
        "f_rest": [0.0] * SH_REST,
        "opacity": opacity,
        "scale": scale,
        "rot": rot,
    }

def make_floater() -> dict:
    """Near-zero opacity, far from the main scene."""
    pos = (random.uniform(-5, 5), random.uniform(-5, 5), random.uniform(-5, 5))
    s = 0.01
    return {
        "pos": pos,
        "normal": (0.0, 0.0, 0.0),
        "f_dc": dc_from_rgb(0.5, 0.5, 0.5),
        "f_rest": [0.0] * SH_REST,
        "opacity": sigmoid_inv(random.uniform(0.01, 0.04)),  # below FLOATER_ALPHA
        "scale": (log_scale(s), log_scale(s), log_scale(s)),
        "rot": (1.0, 0.0, 0.0, 0.0),
    }

def make_outlier() -> dict:
    """Isolated point far from any neighbor, normal opacity."""
    d = random.uniform(4, 8)
    theta = random.uniform(0, math.pi)
    phi = random.uniform(0, 2 * math.pi)
    pos = (d * math.sin(theta) * math.cos(phi),
           d * math.sin(theta) * math.sin(phi),
           d * math.cos(theta))
    s = 0.02
    return {
        "pos": pos,
        "normal": (0.0, 0.0, 0.0),
        "f_dc": dc_from_rgb(0.9, 0.1, 0.1),  # red — visually distinct
        "f_rest": [0.0] * SH_REST,
        "opacity": sigmoid_inv(0.9),
        "scale": (log_scale(s), log_scale(s), log_scale(s)),
        "rot": (1.0, 0.0, 0.0, 0.0),
    }

def make_needle() -> dict:
    """Extreme axis ratio > 10:1 — one scale axis >> the others."""
    pos = (random.uniform(-1.5, 1.5), random.uniform(-1.5, 1.5), random.uniform(-1.5, 1.5))
    s_small = 0.005
    s_big = s_small * (10 + random.uniform(2, 20))  # ratio > 10
    axes = [log_scale(s_small), log_scale(s_small), log_scale(s_small)]
    axes[random.randint(0, 2)] = log_scale(s_big)
    return {
        "pos": pos,
        "normal": (0.0, 0.0, 0.0),
        "f_dc": dc_from_rgb(0.1, 0.1, 0.9),  # blue — visually distinct
        "f_rest": [0.0] * SH_REST,
        "opacity": sigmoid_inv(0.8),
        "scale": tuple(axes),
        "rot": (1.0, 0.0, 0.0, 0.0),
    }

def main():
    out_dir = os.path.dirname(os.path.abspath(__file__))

    # ── Clean scene: 1000 Gaussians on a sphere ──
    clean = []
    n_clean = 1000
    for i in range(n_clean):
        # Fibonacci sphere sampling
        golden = (1 + math.sqrt(5)) / 2
        theta = math.acos(1 - 2 * (i + 0.5) / n_clean)
        phi = 2 * math.pi * i / golden
        clean.append(make_sphere_gaussian(theta, phi))

    write_ply(os.path.join(out_dir, "clean.ply"), clean)

    # ── Messy scene: same sphere + defects ──
    messy = list(clean)  # start with the same clean Gaussians
    for _ in range(80):
        messy.append(make_floater())
    for _ in range(60):
        messy.append(make_outlier())
    for _ in range(60):
        messy.append(make_needle())

    write_ply(os.path.join(out_dir, "messy.ply"), messy)

    print(f"\nclean.ply: {n_clean} Gaussians (sphere)")
    print(f"messy.ply: {len(messy)} Gaussians ({n_clean} sphere + 80 floaters + 60 outliers + 60 needles)")

if __name__ == "__main__":
    main()
