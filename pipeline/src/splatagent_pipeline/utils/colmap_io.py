"""Read/write COLMAP binary model files (cameras, images, points3D).

Binary format reference: https://colmap.github.io/format.html
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np


# ---------------------------------------------------------------------------
# Camera models
# ---------------------------------------------------------------------------

CAMERA_MODEL_IDS = {
    0: ("SIMPLE_PINHOLE", 3),
    1: ("PINHOLE", 4),
    2: ("SIMPLE_RADIAL", 4),
    3: ("RADIAL", 5),
    4: ("OPENCV", 8),
    5: ("OPENCV_FISHEYE", 8),
    6: ("FULL_OPENCV", 12),
    7: ("FOV", 5),
    8: ("SIMPLE_RADIAL_FISHEYE", 4),
    9: ("RADIAL_FISHEYE", 5),
    10: ("THIN_PRISM_FISHEYE", 12),
}


# ---------------------------------------------------------------------------
# Cameras
# ---------------------------------------------------------------------------

def read_cameras_binary(path: Path) -> dict[int, dict]:
    """Read cameras.bin. Returns {camera_id: {model, width, height, params}}."""
    cameras = {}
    with open(path, "rb") as f:
        num_cameras = struct.unpack("<Q", f.read(8))[0]
        for _ in range(num_cameras):
            camera_id = struct.unpack("<I", f.read(4))[0]
            model_id = struct.unpack("<i", f.read(4))[0]
            width = struct.unpack("<Q", f.read(8))[0]
            height = struct.unpack("<Q", f.read(8))[0]
            model_name, num_params = CAMERA_MODEL_IDS[model_id]
            params = struct.unpack(f"<{num_params}d", f.read(8 * num_params))
            cameras[camera_id] = {
                "model": model_name,
                "model_id": model_id,
                "width": width,
                "height": height,
                "params": list(params),
            }
    return cameras


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------

def read_images_binary(path: Path) -> dict[int, dict]:
    """Read images.bin. Returns {image_id: {qvec, tvec, camera_id, name, xys, point3D_ids}}."""
    images = {}
    with open(path, "rb") as f:
        num_images = struct.unpack("<Q", f.read(8))[0]
        for _ in range(num_images):
            image_id = struct.unpack("<I", f.read(4))[0]
            qvec = struct.unpack("<4d", f.read(32))
            tvec = struct.unpack("<3d", f.read(24))
            camera_id = struct.unpack("<I", f.read(4))[0]

            # Image name (null-terminated string)
            name_chars = []
            while True:
                ch = f.read(1)
                if ch == b"\x00":
                    break
                name_chars.append(ch.decode("ascii"))
            name = "".join(name_chars)

            # 2D points
            num_points2D = struct.unpack("<Q", f.read(8))[0]
            xys = []
            point3D_ids = []
            for _ in range(num_points2D):
                x, y = struct.unpack("<2d", f.read(16))
                p3d_id = struct.unpack("<q", f.read(8))[0]
                xys.append((x, y))
                point3D_ids.append(p3d_id)

            images[image_id] = {
                "qvec": np.array(qvec),
                "tvec": np.array(tvec),
                "camera_id": camera_id,
                "name": name,
                "xys": np.array(xys) if xys else np.empty((0, 2)),
                "point3D_ids": np.array(point3D_ids, dtype=np.int64),
            }
    return images


# ---------------------------------------------------------------------------
# Points3D
# ---------------------------------------------------------------------------

def read_points3D_binary(path: Path) -> dict[int, dict]:
    """Read points3D.bin. Returns {point3D_id: {xyz, rgb, error, track}}."""
    points3D = {}
    with open(path, "rb") as f:
        num_points = struct.unpack("<Q", f.read(8))[0]
        for _ in range(num_points):
            point3D_id = struct.unpack("<Q", f.read(8))[0]
            xyz = struct.unpack("<3d", f.read(24))
            rgb = struct.unpack("<3B", f.read(3))
            error = struct.unpack("<d", f.read(8))[0]
            track_length = struct.unpack("<Q", f.read(8))[0]
            track = []
            for _ in range(track_length):
                image_id = struct.unpack("<I", f.read(4))[0]
                point2D_idx = struct.unpack("<I", f.read(4))[0]
                track.append((image_id, point2D_idx))
            points3D[point3D_id] = {
                "xyz": np.array(xyz),
                "rgb": np.array(rgb, dtype=np.uint8),
                "error": error,
                "track": track,
            }
    return points3D


# ---------------------------------------------------------------------------
# Convenience: read full model
# ---------------------------------------------------------------------------

def read_colmap_model(model_dir: Path) -> tuple[dict, dict, dict]:
    """Read a full COLMAP binary model. Returns (cameras, images, points3D)."""
    cameras_path = model_dir / "cameras.bin"
    images_path = model_dir / "images.bin"
    points3D_path = model_dir / "points3D.bin"

    for p in [cameras_path, images_path, points3D_path]:
        if not p.exists():
            raise FileNotFoundError(f"COLMAP model file not found: {p}")

    cameras = read_cameras_binary(cameras_path)
    images = read_images_binary(images_path)
    points3D = read_points3D_binary(points3D_path)

    return cameras, images, points3D


def qvec_to_rotmat(qvec: np.ndarray) -> np.ndarray:
    """Convert COLMAP quaternion (w, x, y, z) to 3x3 rotation matrix."""
    w, x, y, z = qvec
    R = np.array([
        [1 - 2*y*y - 2*z*z, 2*x*y - 2*w*z, 2*x*z + 2*w*y],
        [2*x*y + 2*w*z, 1 - 2*x*x - 2*z*z, 2*y*z - 2*w*x],
        [2*x*z - 2*w*y, 2*y*z + 2*w*x, 1 - 2*x*x - 2*y*y],
    ])
    return R


def get_camera_center(image: dict) -> np.ndarray:
    """Compute camera center in world coordinates from COLMAP image entry."""
    R = qvec_to_rotmat(image["qvec"])
    t = image["tvec"]
    return -R.T @ t
