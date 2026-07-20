"""Pipeline configuration — frozen dataclasses loaded from TOML."""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path
from typing import Literal

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError as exc:
        raise ImportError("Install tomli for Python <3.11: pip install tomli") from exc


# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class VideoIngestConfig:
    fps: float = 2.0
    max_frames: int = 300
    blur_threshold: float = 100.0
    dedup_threshold: float = 0.95


@dataclasses.dataclass(frozen=True)
class ImageIngestConfig:
    max_dimension: int = 1600
    formats: tuple[str, ...] = ("jpg", "jpeg", "png", "webp", "tiff", "bmp")


@dataclasses.dataclass(frozen=True)
class IngestConfig:
    source_type: Literal["images", "video"] = "images"
    source_path: str = ""
    video: VideoIngestConfig = dataclasses.field(default_factory=VideoIngestConfig)
    images: ImageIngestConfig = dataclasses.field(default_factory=ImageIngestConfig)


@dataclasses.dataclass(frozen=True)
class SfMConfig:
    colmap_binary: str = "colmap"
    camera_model: str = "OPENCV"
    single_camera: bool = True
    matcher: Literal["exhaustive", "sequential", "vocab_tree"] = "exhaustive"
    vocab_tree_path: str = ""
    mapper_max_num_models: int = 1
    min_registered_ratio: float = 0.5


@dataclasses.dataclass(frozen=True)
class TrainConfig:
    iterations: int = 30_000
    sh_degree: int = 3
    position_lr_init: float = 0.00016
    position_lr_final: float = 0.0000016
    position_lr_max_steps: int = 30_000
    feature_lr: float = 0.0025
    opacity_lr: float = 0.05
    scaling_lr: float = 0.005
    rotation_lr: float = 0.001
    densify_from_iter: int = 500
    densify_until_iter: int = 15_000
    densify_interval: int = 100
    densify_grad_threshold: float = 0.0002
    prune_opacity_threshold: float = 0.005
    prune_scale_threshold: float = 10.0
    loss_lambda_dssim: float = 0.2
    checkpoint_interval: int = 5_000
    log_interval: int = 100
    eval_interval: int = 1_000
    white_background: bool = False


@dataclasses.dataclass(frozen=True)
class ExportConfig:
    ply_format: str = "standard"
    include_sh_coefficients: bool = True
    max_sh_degree: int = 3


@dataclasses.dataclass(frozen=True)
class RunConfig:
    scene_id: str = ""
    output_dir: str = "./runs"
    resume: bool = True
    seed: int = 42


@dataclasses.dataclass(frozen=True)
class PipelineConfig:
    run: RunConfig = dataclasses.field(default_factory=RunConfig)
    ingest: IngestConfig = dataclasses.field(default_factory=IngestConfig)
    sfm: SfMConfig = dataclasses.field(default_factory=SfMConfig)
    train: TrainConfig = dataclasses.field(default_factory=TrainConfig)
    export: ExportConfig = dataclasses.field(default_factory=ExportConfig)


# ---------------------------------------------------------------------------
# TOML loading helpers
# ---------------------------------------------------------------------------

def _merge_dataclass(cls: type, data: dict) -> dict:
    """Recursively build constructor kwargs from a TOML dict, ignoring unknown keys."""
    fields = {f.name: f for f in dataclasses.fields(cls)}
    kwargs: dict = {}
    for key, value in data.items():
        if key not in fields:
            continue
        field = fields[key]
        # If the field type is itself a dataclass, recurse
        if dataclasses.is_dataclass(field.type if isinstance(field.type, type) else None):
            kwargs[key] = field.type(**_merge_dataclass(field.type, value))
        elif isinstance(value, dict):
            # Try to resolve string type annotations to actual classes
            field_type = _resolve_type(cls, key)
            if field_type and dataclasses.is_dataclass(field_type):
                kwargs[key] = field_type(**_merge_dataclass(field_type, value))
            else:
                kwargs[key] = value
        elif isinstance(value, list) and fields[key].type in (tuple, "tuple[str, ...]"):
            kwargs[key] = tuple(value)
        else:
            # Coerce types for CLI string overrides
            kwargs[key] = _coerce_field_value(field, value)
    return kwargs


def _coerce_field_value(field: dataclasses.Field, value: object) -> object:
    """Coerce a value to match the field's declared type."""
    if isinstance(value, str):
        ft = field.type
        # Handle common type annotations
        if ft in (float, "float"):
            return float(value)
        if ft in (int, "int"):
            return int(value)
        if ft in (bool, "bool"):
            return value.lower() in ("true", "1", "yes")
    return value


def _resolve_type(cls: type, field_name: str) -> type | None:
    """Resolve the actual type of a dataclass field by name."""
    for f in dataclasses.fields(cls):
        if f.name == field_name:
            ft = f.type
            if isinstance(ft, type) and dataclasses.is_dataclass(ft):
                return ft
            # Handle string annotations
            if isinstance(ft, str):
                # Look up in the module globals
                import splatagent_pipeline.config as mod
                resolved = getattr(mod, ft, None)
                if resolved and dataclasses.is_dataclass(resolved):
                    return resolved
    return None


def load_config(path: Path | None = None, overrides: dict | None = None) -> PipelineConfig:
    """Load config from a TOML file, apply overrides, return frozen PipelineConfig."""
    raw: dict = {}
    if path is not None:
        with open(path, "rb") as f:
            raw = tomllib.load(f)

    # Apply flat overrides like {"train.iterations": 50000}
    if overrides:
        for dotted_key, value in overrides.items():
            parts = dotted_key.split(".")
            d = raw
            for part in parts[:-1]:
                d = d.setdefault(part, {})
            d[parts[-1]] = value

    # Build each section
    run_kwargs = _merge_dataclass(RunConfig, raw.get("run", {}))
    ingest_raw = raw.get("ingest", {})
    video_kwargs = _merge_dataclass(VideoIngestConfig, ingest_raw.pop("video", {}))
    images_kwargs = _merge_dataclass(ImageIngestConfig, ingest_raw.pop("images", {}))
    ingest_kwargs = _merge_dataclass(IngestConfig, ingest_raw)

    sfm_kwargs = _merge_dataclass(SfMConfig, raw.get("sfm", {}))
    train_kwargs = _merge_dataclass(TrainConfig, raw.get("train", {}))
    export_kwargs = _merge_dataclass(ExportConfig, raw.get("export", {}))

    return PipelineConfig(
        run=RunConfig(**run_kwargs),
        ingest=IngestConfig(
            **ingest_kwargs,
            video=VideoIngestConfig(**video_kwargs),
            images=ImageIngestConfig(**images_kwargs),
        ),
        sfm=SfMConfig(**sfm_kwargs),
        train=TrainConfig(**train_kwargs),
        export=ExportConfig(**export_kwargs),
    )


def config_to_dict(config: PipelineConfig) -> dict:
    """Recursively convert a frozen config to a plain dict (for JSON serialization)."""
    return dataclasses.asdict(config)
