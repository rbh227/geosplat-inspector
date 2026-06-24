"""Stage 4 — Export: write .ply and manifest.json."""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from ..config import PipelineConfig, config_to_dict
from ..logging_setup import get_logger
from ..manifest import (
    BoundsInfo,
    Manifest,
    OutputInfo,
    SfMInfo,
    SourceInfo,
    ToolchainInfo,
    TrainingInfo,
)
from ..utils.ply_io import write_ply


class ExportError(Exception):
    pass


STAGE_MARKER = "output/manifest.json"


def is_complete(run_dir: Path) -> bool:
    ply_path = run_dir / "output" / "scene.ply"
    manifest_path = run_dir / STAGE_MARKER
    return ply_path.exists() and manifest_path.exists()


def _get_tool_version(cmd: list[str]) -> str:
    """Safely get version string from a CLI tool."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return result.stdout.split("\n")[0].strip()
    except Exception:
        return "unknown"


def _get_toolchain_info() -> ToolchainInfo:
    """Collect versions of all tools in the pipeline."""
    import torch

    from .. import __version__

    cuda_version = ""
    if torch.cuda.is_available():
        cuda_version = torch.version.cuda or ""

    gsplat_version = "unknown"
    try:
        import gsplat
        gsplat_version = getattr(gsplat, "__version__", "installed")
    except ImportError:
        gsplat_version = "not installed"

    colmap_version = _get_tool_version(["colmap", "-h"])
    ffmpeg_version = _get_tool_version(["ffmpeg", "-version"])

    return ToolchainInfo(
        python_version=platform.python_version(),
        gsplat_version=gsplat_version,
        colmap_version=colmap_version,
        torch_version=torch.__version__,
        cuda_version=cuda_version,
        pipeline_version=__version__,
        ffmpeg_version=ffmpeg_version,
    )


def run_export(config: PipelineConfig, run_dir: Path, scene_id: str) -> dict:
    """Run the export stage: write PLY + manifest."""
    log = get_logger()

    if config.run.resume and is_complete(run_dir):
        log.info("[bold green]Stage 4 (Export): skipping — already complete[/]")
        with open(run_dir / STAGE_MARKER) as f:
            return json.load(f)

    log.info("[bold cyan]Stage 4 (Export): starting[/]")

    output_dir = run_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load trained model
    model_path = run_dir / "train" / "final_model.pt"
    if not model_path.exists():
        raise ExportError(f"Trained model not found at {model_path}. Run the train stage first.")

    import numpy as np
    import torch

    log.info(f"Loading trained model from {model_path.name}")
    data = torch.load(model_path, map_location="cpu", weights_only=True)

    means = data["means"].numpy().astype(np.float32)        # (N, 3)
    scales = data["scales"].numpy().astype(np.float32)       # (N, 3) log-space
    rotations = data["rotations"].numpy().astype(np.float32) # (N, 4) wxyz
    opacities = data["opacities"].numpy().astype(np.float32) # (N, 1) logit
    sh_dc = data["sh_dc"].numpy().astype(np.float32)         # (N, 1, 3)
    sh_rest = data["sh_rest"].numpy().astype(np.float32)     # (N, K, 3)

    # Reshape sh_dc from (N, 1, 3) to (N, 3)
    sh_dc_flat = sh_dc.squeeze(1)

    n = means.shape[0]
    log.info(f"Exporting {n} Gaussians to PLY")

    # Write PLY — coordinates stay in COLMAP convention (Y-down)
    ply_path = output_dir / "scene.ply"
    write_ply(
        path=ply_path,
        means=means,
        scales=scales,
        rotations=rotations,
        opacities=opacities,
        sh_dc=sh_dc_flat,
        sh_rest=sh_rest,
        sh_degree=config.export.max_sh_degree,
    )
    ply_size = ply_path.stat().st_size

    # Compute bounds
    bounds_min = means.min(axis=0).tolist()
    bounds_max = means.max(axis=0).tolist()

    # Load stage reports
    ingest_report = _load_report(run_dir / "ingest_report.json")
    sfm_report = _load_report(run_dir / "sfm_report.json")
    train_report = _load_report(run_dir / "train_report.json")

    # Build manifest
    manifest = Manifest(
        scene_id=scene_id,
        source=SourceInfo(
            type=ingest_report.get("source_type", ""),
            frame_count=ingest_report.get("final_frame_count", 0),
            image_dimensions=tuple(ingest_report.get("image_dimensions", [0, 0])),
        ),
        sfm=SfMInfo(
            registered_images=sfm_report.get("registered_images", 0),
            sparse_points=sfm_report.get("sparse_points", 0),
            mean_reprojection_error=sfm_report.get("mean_reprojection_error", 0.0),
        ),
        training=TrainingInfo(
            iterations=train_report.get("iterations", 0),
            final_gaussians=train_report.get("final_gaussians", 0),
            final_psnr=train_report.get("final_psnr", 0.0),
            final_ssim=train_report.get("final_ssim", 0.0),
            training_time_seconds=train_report.get("training_time_seconds", 0.0),
        ),
        bounds=BoundsInfo(min=bounds_min, max=bounds_max),
        output=OutputInfo(
            ply_file="scene.ply",
            ply_size_bytes=ply_size,
            coordinate_convention="colmap_y_down",
        ),
        toolchain=_get_toolchain_info(),
        config_snapshot=config_to_dict(config),
    )

    manifest_path = output_dir / "manifest.json"
    manifest.write(manifest_path)

    log.info(
        f"[bold green]Stage 4 (Export): complete — {ply_path.name} "
        f"({ply_size / 1024 / 1024:.1f} MB), manifest written[/]"
    )

    # Return manifest as dict
    with open(manifest_path) as f:
        return json.load(f)


def _load_report(path: Path) -> dict:
    """Safely load a stage report JSON."""
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}
