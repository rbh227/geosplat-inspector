"""FFmpeg wrapper for video frame extraction."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from ..logging_setup import get_logger


class VideoError(Exception):
    pass


def check_ffmpeg() -> str:
    """Return ffmpeg version string, or raise VideoError if not found."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise VideoError("ffmpeg not found on PATH. Install: brew install ffmpeg (macOS) or apt install ffmpeg (Linux)")
    result = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True)
    first_line = result.stdout.split("\n")[0]
    return first_line


def get_video_info(video_path: Path) -> dict:
    """Probe video for duration, fps, resolution using ffprobe."""
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        raise VideoError("ffprobe not found on PATH (installed with ffmpeg)")

    cmd = [
        ffprobe, "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        str(video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise VideoError(f"ffprobe failed on {video_path}: {result.stderr}")

    data = json.loads(result.stdout)
    video_stream = None
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            video_stream = stream
            break

    if video_stream is None:
        raise VideoError(f"No video stream found in {video_path}")

    duration = float(data.get("format", {}).get("duration", 0))
    width = int(video_stream.get("width", 0))
    height = int(video_stream.get("height", 0))

    # Parse frame rate (e.g. "30000/1001" or "30/1")
    r_frame_rate = video_stream.get("r_frame_rate", "0/1")
    num, den = map(int, r_frame_rate.split("/"))
    native_fps = num / den if den else 0

    return {
        "duration": duration,
        "width": width,
        "height": height,
        "native_fps": native_fps,
        "codec": video_stream.get("codec_name", "unknown"),
    }


def extract_frames(
    video_path: Path,
    output_dir: Path,
    fps: float = 2.0,
    max_frames: int = 300,
) -> list[Path]:
    """Extract frames from video at given fps. Returns list of extracted frame paths."""
    log = get_logger()

    if not video_path.is_file():
        raise VideoError(f"Video file not found: {video_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_pattern = str(output_dir / "frame_%06d.jpg")

    info = get_video_info(video_path)
    log.info(
        f"Video: {info['width']}x{info['height']}, {info['duration']:.1f}s, "
        f"{info['native_fps']:.1f}fps, codec={info['codec']}"
    )

    expected_frames = int(info["duration"] * fps)
    if expected_frames > max_frames:
        # Adjust fps to stay under max_frames
        adjusted_fps = max_frames / info["duration"]
        log.info(f"Adjusting extraction rate from {fps} to {adjusted_fps:.2f} fps to cap at {max_frames} frames")
        fps = adjusted_fps

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vf", f"fps={fps}",
        "-qscale:v", "2",
        output_pattern,
    ]
    log.info(f"Extracting frames: {' '.join(cmd)}")

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise VideoError(f"ffmpeg frame extraction failed: {result.stderr[:500]}")

    frames = sorted(output_dir.glob("frame_*.jpg"))
    if not frames:
        raise VideoError("ffmpeg produced no output frames")

    # Enforce max_frames cap
    if len(frames) > max_frames:
        for f in frames[max_frames:]:
            f.unlink()
        frames = frames[:max_frames]

    log.info(f"Extracted {len(frames)} frames")
    return frames
