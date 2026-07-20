"""Manifest schema and JSON serialization.

The manifest is the contract between the pipeline and the frontend viewer.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class SourceInfo:
    type: str = ""          # "images" or "video"
    frame_count: int = 0
    image_dimensions: tuple[int, int] = (0, 0)


@dataclass
class SfMInfo:
    registered_images: int = 0
    sparse_points: int = 0
    mean_reprojection_error: float = 0.0


@dataclass
class TrainingInfo:
    iterations: int = 0
    final_gaussians: int = 0
    final_psnr: float = 0.0
    final_ssim: float = 0.0
    training_time_seconds: float = 0.0


@dataclass
class BoundsInfo:
    min: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    max: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])


@dataclass
class OutputInfo:
    ply_file: str = "scene.ply"
    ply_size_bytes: int = 0
    coordinate_convention: str = "colmap_y_down"


@dataclass
class ToolchainInfo:
    python_version: str = ""
    gsplat_version: str = ""
    colmap_version: str = ""
    torch_version: str = ""
    cuda_version: str = ""
    pipeline_version: str = ""
    ffmpeg_version: str = ""


@dataclass
class Manifest:
    schema_version: str = "1.0"
    scene_id: str = ""
    created_at: str = ""
    source: SourceInfo = field(default_factory=SourceInfo)
    sfm: SfMInfo = field(default_factory=SfMInfo)
    training: TrainingInfo = field(default_factory=TrainingInfo)
    bounds: BoundsInfo = field(default_factory=BoundsInfo)
    output: OutputInfo = field(default_factory=OutputInfo)
    toolchain: ToolchainInfo = field(default_factory=ToolchainInfo)
    config_snapshot: dict = field(default_factory=dict)

    def write(self, path: Path) -> None:
        """Write manifest to JSON file."""
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2, default=str)

    @classmethod
    def read(cls, path: Path) -> Manifest:
        """Read manifest from JSON file."""
        with open(path) as f:
            data = json.load(f)
        return _dict_to_manifest(data)


def _dict_to_manifest(data: dict) -> Manifest:
    """Reconstruct a Manifest from a plain dict."""
    return Manifest(
        schema_version=data.get("schema_version", "1.0"),
        scene_id=data.get("scene_id", ""),
        created_at=data.get("created_at", ""),
        source=SourceInfo(**{k: v for k, v in data.get("source", {}).items()
                            if k in SourceInfo.__dataclass_fields__}),
        sfm=SfMInfo(**{k: v for k, v in data.get("sfm", {}).items()
                      if k in SfMInfo.__dataclass_fields__}),
        training=TrainingInfo(**{k: v for k, v in data.get("training", {}).items()
                                if k in TrainingInfo.__dataclass_fields__}),
        bounds=BoundsInfo(**{k: v for k, v in data.get("bounds", {}).items()
                            if k in BoundsInfo.__dataclass_fields__}),
        output=OutputInfo(**{k: v for k, v in data.get("output", {}).items()
                            if k in OutputInfo.__dataclass_fields__}),
        toolchain=ToolchainInfo(**{k: v for k, v in data.get("toolchain", {}).items()
                                  if k in ToolchainInfo.__dataclass_fields__}),
        config_snapshot=data.get("config_snapshot", {}),
    )
