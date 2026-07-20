"""Image processing utilities: blur detection, resize, dedup, format normalization."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from ..logging_setup import get_logger


class ImageError(Exception):
    pass


def compute_blur_score(image_path: Path) -> float:
    """Compute Laplacian variance as a blur metric. Higher = sharper."""
    img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ImageError(f"Cannot read image: {image_path}")
    return float(cv2.Laplacian(img, cv2.CV_64F).var())


def resize_if_needed(image_path: Path, max_dimension: int, output_path: Path) -> tuple[int, int]:
    """Resize image so longest edge <= max_dimension. Returns (width, height) of output.

    Saves as JPEG to output_path. If no resize needed and input is JPEG,
    copies as-is.
    """
    img = Image.open(image_path)
    w, h = img.size

    if max(w, h) > max_dimension:
        scale = max_dimension / max(w, h)
        new_w = int(w * scale)
        new_h = int(h * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        w, h = new_w, new_h

    # Ensure RGB (drop alpha, handle grayscale)
    if img.mode != "RGB":
        img = img.convert("RGB")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "JPEG", quality=95)
    return (w, h)


def compute_image_hash(image_path: Path, hash_size: int = 16) -> np.ndarray:
    """Compute a simple average hash for deduplication."""
    img = Image.open(image_path).convert("L").resize((hash_size, hash_size), Image.LANCZOS)
    pixels = np.array(img)
    avg = pixels.mean()
    return (pixels > avg).flatten()


def hash_similarity(h1: np.ndarray, h2: np.ndarray) -> float:
    """Compute similarity between two image hashes (0.0 to 1.0)."""
    return float(np.mean(h1 == h2))


def filter_frames(
    frame_paths: list[Path],
    blur_threshold: float = 100.0,
    dedup_threshold: float = 0.95,
) -> tuple[list[Path], list[dict]]:
    """Filter frames by blur and deduplication.

    Returns (kept_paths, skip_report) where skip_report is a list of
    dicts with {path, reason, score} for each skipped frame.
    """
    log = get_logger()
    kept: list[Path] = []
    skipped: list[dict] = []
    prev_hash: np.ndarray | None = None

    for frame_path in frame_paths:
        # Blur check
        try:
            blur_score = compute_blur_score(frame_path)
        except ImageError:
            skipped.append({"path": str(frame_path), "reason": "unreadable"})
            continue

        if blur_score < blur_threshold:
            skipped.append({
                "path": str(frame_path),
                "reason": "blur",
                "score": round(blur_score, 2),
            })
            continue

        # Dedup check
        if dedup_threshold < 1.0:
            current_hash = compute_image_hash(frame_path)
            if prev_hash is not None:
                sim = hash_similarity(prev_hash, current_hash)
                if sim >= dedup_threshold:
                    skipped.append({
                        "path": str(frame_path),
                        "reason": "duplicate",
                        "score": round(sim, 4),
                    })
                    continue
            prev_hash = current_hash

        kept.append(frame_path)

    log.info(f"Frame filtering: {len(kept)} kept, {len(skipped)} skipped")
    return kept, skipped
