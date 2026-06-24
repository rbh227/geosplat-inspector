"""Stage 1 — Ingestion: validate, normalize, and prepare frames from images or video."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from ..config import PipelineConfig
from ..logging_setup import get_logger
from ..utils.image_utils import ImageError, compute_blur_score, filter_frames, resize_if_needed
from ..utils.video_utils import VideoError, check_ffmpeg, extract_frames


class IngestError(Exception):
    pass


STAGE_MARKER = "ingest_report.json"
MIN_FRAMES = 3


def is_complete(run_dir: Path) -> bool:
    """Check if ingestion was already completed."""
    marker = run_dir / STAGE_MARKER
    images_dir = run_dir / "images"
    return marker.exists() and images_dir.exists() and any(images_dir.iterdir())


def run_ingest(config: PipelineConfig, run_dir: Path) -> dict:
    """Run the ingestion stage.

    Returns the ingest report dict (also written to disk).
    """
    log = get_logger()
    images_dir = run_dir / "images"

    if config.run.resume and is_complete(run_dir):
        log.info("[bold green]Stage 1 (Ingest): skipping — already complete[/]")
        with open(run_dir / STAGE_MARKER) as f:
            return json.load(f)

    log.info("[bold cyan]Stage 1 (Ingest): starting[/]")
    images_dir.mkdir(parents=True, exist_ok=True)

    source_type = config.ingest.source_type
    source_path = Path(config.ingest.source_path)

    if source_type == "video":
        report = _ingest_video(config, source_path, images_dir)
    elif source_type == "images":
        report = _ingest_images(config, source_path, images_dir)
    else:
        raise IngestError(f"Unknown source_type: {source_type}")

    # Validate minimum frame count
    final_frames = sorted(images_dir.glob("frame_*.jpg"))
    if len(final_frames) < MIN_FRAMES:
        raise IngestError(
            f"Only {len(final_frames)} frames after filtering; need at least {MIN_FRAMES}. "
            "Try lowering blur_threshold or providing more input images/longer video."
        )

    report["final_frame_count"] = len(final_frames)
    report["source_type"] = source_type
    report["source_path"] = str(source_path)

    # Record image dimensions from first frame
    from PIL import Image
    with Image.open(final_frames[0]) as img:
        report["image_dimensions"] = list(img.size)

    # Write report
    report_path = run_dir / STAGE_MARKER
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    log.info(f"[bold green]Stage 1 (Ingest): complete — {report['final_frame_count']} frames[/]")
    return report


def _ingest_video(config: PipelineConfig, video_path: Path, images_dir: Path) -> dict:
    """Extract and filter frames from a video file."""
    log = get_logger()

    if not video_path.is_file():
        raise IngestError(f"Video file not found: {video_path}")

    # Check ffmpeg
    try:
        ffmpeg_version = check_ffmpeg()
    except VideoError as e:
        raise IngestError(str(e)) from e

    vc = config.ingest.video

    # Extract raw frames to a temp directory, then filter
    raw_dir = images_dir.parent / "_raw_frames"
    raw_dir.mkdir(parents=True, exist_ok=True)

    try:
        raw_frames = extract_frames(video_path, raw_dir, fps=vc.fps, max_frames=vc.max_frames)
    except VideoError as e:
        raise IngestError(f"Frame extraction failed: {e}") from e

    # Filter by blur and dedup
    kept, skipped = filter_frames(
        raw_frames,
        blur_threshold=vc.blur_threshold,
        dedup_threshold=vc.dedup_threshold,
    )

    # Normalize: resize and rename sequentially into images_dir
    ic = config.ingest.images
    for i, frame_path in enumerate(kept, 1):
        output_path = images_dir / f"frame_{i:06d}.jpg"
        resize_if_needed(frame_path, ic.max_dimension, output_path)

    # Clean up raw frames
    shutil.rmtree(raw_dir, ignore_errors=True)

    return {
        "raw_frame_count": len(raw_frames),
        "skipped": [s for s in skipped],
        "skipped_count": len(skipped),
        "ffmpeg_version": ffmpeg_version,
    }


def _ingest_images(config: PipelineConfig, source_dir: Path, images_dir: Path) -> dict:
    """Validate and normalize a directory of images."""
    log = get_logger()

    if not source_dir.is_dir():
        raise IngestError(f"Image directory not found: {source_dir}")

    ic = config.ingest.images
    valid_exts = set(f".{fmt}" for fmt in ic.formats)

    # Collect valid image paths
    raw_paths: list[Path] = []
    for f in sorted(source_dir.iterdir()):
        if f.suffix.lower() in valid_exts and f.is_file():
            raw_paths.append(f)

    if not raw_paths:
        raise IngestError(
            f"No valid images found in {source_dir}. "
            f"Expected formats: {', '.join(ic.formats)}"
        )

    log.info(f"Found {len(raw_paths)} images in {source_dir}")

    # Filter by blur (skip dedup for images — user likely curated them)
    vc = config.ingest.video
    kept, skipped = filter_frames(
        raw_paths,
        blur_threshold=vc.blur_threshold,
        dedup_threshold=1.0,  # No dedup for image folders
    )

    # Normalize: resize and rename sequentially
    for i, frame_path in enumerate(kept, 1):
        output_path = images_dir / f"frame_{i:06d}.jpg"
        resize_if_needed(frame_path, ic.max_dimension, output_path)

    return {
        "raw_image_count": len(raw_paths),
        "skipped": [s for s in skipped],
        "skipped_count": len(skipped),
    }
