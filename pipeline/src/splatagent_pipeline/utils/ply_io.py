"""PLY read/write for standard 3D Gaussian Splat format.

The PLY stores per-Gaussian parameters in their raw/internal form:
  - positions: world-space (x, y, z)
  - normals: placeholder zeros (nx, ny, nz)
  - SH DC: f_dc_0, f_dc_1, f_dc_2
  - SH rest: f_rest_0 .. f_rest_{3*(degree+1)^2 - 4}  (44 for degree=3)
  - opacity: raw logit (before sigmoid)
  - scale: log-scale (before exp)
  - rotation: quaternion (rot_0..rot_3), wxyz convention
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np


def write_ply(
    path: Path,
    means: np.ndarray,       # (N, 3) float32
    scales: np.ndarray,      # (N, 3) float32 — log-space
    rotations: np.ndarray,   # (N, 4) float32 — quaternion wxyz
    opacities: np.ndarray,   # (N, 1) float32 — logit
    sh_dc: np.ndarray,       # (N, 3) float32
    sh_rest: np.ndarray | None = None,  # (N, C, 3) float32
    sh_degree: int = 3,
) -> int:
    """Write a standard 3DGS PLY file. Returns number of vertices written."""
    n = means.shape[0]
    assert means.shape == (n, 3)
    assert scales.shape == (n, 3)
    assert rotations.shape == (n, 4)
    assert opacities.shape == (n, 1) or opacities.shape == (n,)
    assert sh_dc.shape == (n, 3)

    if opacities.ndim == 1:
        opacities = opacities[:, None]

    # Number of SH rest coefficients per Gaussian
    num_sh_rest = 3 * ((sh_degree + 1) ** 2 - 1)  # 44 for degree 3
    if sh_rest is not None:
        # sh_rest comes as (N, K, 3) where K = (degree+1)^2 - 1
        # Flatten to (N, K*3) interleaved
        sh_rest_flat = sh_rest.reshape(n, -1).astype(np.float32)
        assert sh_rest_flat.shape[1] == num_sh_rest, (
            f"Expected {num_sh_rest} SH rest coeffs, got {sh_rest_flat.shape[1]}"
        )
    else:
        sh_rest_flat = np.zeros((n, num_sh_rest), dtype=np.float32)

    normals = np.zeros((n, 3), dtype=np.float32)

    # Build header
    header_lines = [
        "ply",
        "format binary_little_endian 1.0",
        f"element vertex {n}",
        "property float x",
        "property float y",
        "property float z",
        "property float nx",
        "property float ny",
        "property float nz",
        "property float f_dc_0",
        "property float f_dc_1",
        "property float f_dc_2",
    ]
    for i in range(num_sh_rest):
        header_lines.append(f"property float f_rest_{i}")
    header_lines += [
        "property float opacity",
        "property float scale_0",
        "property float scale_1",
        "property float scale_2",
        "property float rot_0",
        "property float rot_1",
        "property float rot_2",
        "property float rot_3",
        "end_header",
    ]
    header = "\n".join(header_lines) + "\n"

    # Write binary
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(header.encode("ascii"))
        for i in range(n):
            # x y z
            f.write(struct.pack("<3f", *means[i]))
            # nx ny nz
            f.write(struct.pack("<3f", *normals[i]))
            # f_dc_0 f_dc_1 f_dc_2
            f.write(struct.pack("<3f", *sh_dc[i]))
            # f_rest_0 .. f_rest_{num_sh_rest-1}
            f.write(struct.pack(f"<{num_sh_rest}f", *sh_rest_flat[i]))
            # opacity
            f.write(struct.pack("<f", opacities[i, 0]))
            # scale_0 scale_1 scale_2
            f.write(struct.pack("<3f", *scales[i]))
            # rot_0 rot_1 rot_2 rot_3
            f.write(struct.pack("<4f", *rotations[i]))

    return n


def read_ply(path: Path, sh_degree: int = 3) -> dict[str, np.ndarray]:
    """Read a standard 3DGS PLY file. Returns dict of numpy arrays."""
    with open(path, "rb") as f:
        # Parse header
        header_lines: list[str] = []
        while True:
            line = f.readline().decode("ascii").strip()
            header_lines.append(line)
            if line == "end_header":
                break

        # Extract vertex count
        num_vertices = 0
        for line in header_lines:
            if line.startswith("element vertex"):
                num_vertices = int(line.split()[-1])
                break
        assert num_vertices > 0, "No vertices found in PLY header"

        num_sh_rest = 3 * ((sh_degree + 1) ** 2 - 1)
        # Properties: 3 pos + 3 normal + 3 dc + num_sh_rest + 1 opacity + 3 scale + 4 rot
        num_props = 3 + 3 + 3 + num_sh_rest + 1 + 3 + 4
        bytes_per_vertex = num_props * 4  # all float32

        data = np.frombuffer(f.read(num_vertices * bytes_per_vertex), dtype=np.float32)
        data = data.reshape(num_vertices, num_props)

    idx = 0
    means = data[:, idx:idx + 3]; idx += 3
    _normals = data[:, idx:idx + 3]; idx += 3  # noqa: F841
    sh_dc = data[:, idx:idx + 3]; idx += 3
    sh_rest_flat = data[:, idx:idx + num_sh_rest]; idx += num_sh_rest
    opacities = data[:, idx:idx + 1]; idx += 1
    scales = data[:, idx:idx + 3]; idx += 3
    rotations = data[:, idx:idx + 4]; idx += 4

    # Reshape SH rest from (N, K*3) to (N, K, 3)
    k = (sh_degree + 1) ** 2 - 1
    sh_rest = sh_rest_flat.reshape(num_vertices, k, 3) if k > 0 else None

    return {
        "means": means.copy(),
        "scales": scales.copy(),
        "rotations": rotations.copy(),
        "opacities": opacities.copy(),
        "sh_dc": sh_dc.copy(),
        "sh_rest": sh_rest.copy() if sh_rest is not None else None,
    }
