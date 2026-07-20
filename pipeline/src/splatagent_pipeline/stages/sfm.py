"""Stage 2 — Structure from Motion: COLMAP feature extraction, matching, and mapping."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from ..config import PipelineConfig
from ..logging_setup import get_logger
from ..utils.colmap_io import read_colmap_model


class SfMError(Exception):
    pass


STAGE_MARKER = "sfm_report.json"


def is_complete(run_dir: Path) -> bool:
    """Check if SfM was already completed."""
    marker = run_dir / STAGE_MARKER
    model_dir = run_dir / "sparse" / "0"
    return (
        marker.exists()
        and model_dir.exists()
        and (model_dir / "cameras.bin").exists()
        and (model_dir / "images.bin").exists()
        and (model_dir / "points3D.bin").exists()
    )


def _check_colmap(binary: str) -> str:
    """Verify COLMAP is available. Returns version string."""
    colmap_path = shutil.which(binary) or binary
    try:
        result = subprocess.run(
            [colmap_path, "-h"],
            capture_output=True, text=True, timeout=10,
        )
    except FileNotFoundError:
        raise SfMError(
            f"COLMAP not found at '{binary}'. Install COLMAP: https://colmap.github.io/install.html"
        )
    except subprocess.TimeoutExpired:
        raise SfMError(f"COLMAP at '{binary}' timed out on version check")

    # Try to get version
    try:
        ver_result = subprocess.run(
            [colmap_path, "help"],
            capture_output=True, text=True, timeout=10,
        )
        # COLMAP prints version in first line of help
        first_line = ver_result.stdout.split("\n")[0] if ver_result.stdout else "unknown"
    except Exception:
        first_line = "unknown"

    return first_line


def _run_colmap_cmd(cmd: list[str], step_name: str) -> None:
    """Run a COLMAP subprocess command with logging and error handling."""
    log = get_logger()
    cmd_str = " ".join(cmd)
    log.info(f"  COLMAP {step_name}: {cmd_str}")

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)

    if result.returncode != 0:
        stderr_snippet = result.stderr[-1000:] if result.stderr else "(no stderr)"
        raise SfMError(
            f"COLMAP {step_name} failed (exit code {result.returncode}).\n"
            f"Command: {cmd_str}\n"
            f"stderr: {stderr_snippet}"
        )


def run_sfm(config: PipelineConfig, run_dir: Path) -> dict:
    """Run the SfM stage.

    Returns the SfM report dict (also written to disk).
    """
    log = get_logger()

    if config.run.resume and is_complete(run_dir):
        log.info("[bold green]Stage 2 (SfM): skipping — already complete[/]")
        with open(run_dir / STAGE_MARKER) as f:
            return json.load(f)

    log.info("[bold cyan]Stage 2 (SfM): starting[/]")

    images_dir = run_dir / "images"
    if not images_dir.exists() or not any(images_dir.iterdir()):
        raise SfMError("No images found. Run the ingest stage first.")

    sc = config.sfm
    colmap = shutil.which(sc.colmap_binary) or sc.colmap_binary
    colmap_version = _check_colmap(colmap)

    database_path = run_dir / "database.db"
    sparse_dir = run_dir / "sparse"
    sparse_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Feature extraction
    feature_cmd = [
        colmap, "feature_extractor",
        "--database_path", str(database_path),
        "--image_path", str(images_dir),
        "--ImageReader.camera_model", sc.camera_model,
        "--ImageReader.single_camera", "1" if sc.single_camera else "0",
    ]
    _run_colmap_cmd(feature_cmd, "feature_extractor")

    # Step 2: Feature matching
    matcher_type = f"{sc.matcher}_matcher"
    match_cmd = [
        colmap, matcher_type,
        "--database_path", str(database_path),
    ]
    if sc.matcher == "vocab_tree" and sc.vocab_tree_path:
        match_cmd += ["--VocabTreeMatching.vocab_tree_path", sc.vocab_tree_path]
    if sc.matcher == "sequential":
        match_cmd += ["--SequentialMatching.overlap", "10"]
    _run_colmap_cmd(match_cmd, matcher_type)

    # Step 3: Mapper (incremental SfM)
    mapper_cmd = [
        colmap, "mapper",
        "--database_path", str(database_path),
        "--image_path", str(images_dir),
        "--output_path", str(sparse_dir),
        "--Mapper.max_num_models", str(sc.mapper_max_num_models),
    ]
    _run_colmap_cmd(mapper_cmd, "mapper")

    # Validate results
    model_dir = sparse_dir / "0"
    if not model_dir.exists():
        raise SfMError(
            "COLMAP mapper produced no reconstruction. "
            "Images may lack texture, have insufficient overlap, or contain "
            "degenerate motion (pure rotation)."
        )

    cameras, images, points3D = read_colmap_model(model_dir)

    # Count registered images
    total_images = len(list(images_dir.glob("frame_*.jpg")))
    registered = len(images)
    ratio = registered / total_images if total_images > 0 else 0.0

    if ratio < sc.min_registered_ratio:
        raise SfMError(
            f"Only {registered}/{total_images} images registered ({ratio:.1%}). "
            f"Minimum required: {sc.min_registered_ratio:.0%}. "
            "Try more images or different matching strategy."
        )

    # Compute mean reprojection error
    errors = [p["error"] for p in points3D.values()]
    mean_error = float(sum(errors) / len(errors)) if errors else 0.0

    report = {
        "colmap_version": colmap_version,
        "total_images": total_images,
        "registered_images": registered,
        "registration_ratio": round(ratio, 4),
        "sparse_points": len(points3D),
        "mean_reprojection_error": round(mean_error, 4),
        "num_cameras": len(cameras),
        "camera_model": list(cameras.values())[0]["model"] if cameras else "unknown",
    }

    # Write report
    report_path = run_dir / STAGE_MARKER
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    log.info(
        f"[bold green]Stage 2 (SfM): complete — {registered}/{total_images} images, "
        f"{len(points3D)} points[/]"
    )
    return report
