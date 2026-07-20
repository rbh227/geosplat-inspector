"""CLI entry point for the SplatAgent pipeline."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from .config import PipelineConfig, load_config
from .runner import PipelineError, PipelineRunner


@click.group()
@click.version_option(package_name="splatagent-pipeline")
def cli() -> None:
    """SplatAgent Pipeline — Generate Gaussian Splats from images or video."""
    pass


@cli.command()
@click.option("--source", type=click.Choice(["images", "video"]), required=True,
              help="Input source type.")
@click.option("--input", "input_path", type=click.Path(exists=True), required=True,
              help="Path to images directory or video file.")
@click.option("--config", "config_path", type=click.Path(exists=True), default=None,
              help="Path to TOML config file.")
@click.option("--output-dir", type=click.Path(), default="./runs",
              help="Base output directory.")
@click.option("--scene-id", default=None,
              help="Custom scene ID (default: auto-generated UUID).")
@click.option("--iterations", type=int, default=None,
              help="Override training iterations.")
@click.option("--resume", "resume_dir", type=click.Path(exists=True), default=None,
              help="Resume a previous run from its directory.")
def run(
    source: str,
    input_path: str,
    config_path: str | None,
    output_dir: str,
    scene_id: str | None,
    iterations: int | None,
    resume_dir: str | None,
) -> None:
    """Run the full generation pipeline."""
    overrides: dict = {
        "ingest.source_type": source,
        "ingest.source_path": str(Path(input_path).resolve()),
        "run.output_dir": output_dir,
    }
    if scene_id:
        overrides["run.scene_id"] = scene_id
    if iterations:
        overrides["train.iterations"] = iterations

    config_file = Path(config_path) if config_path else None
    config = load_config(config_file, overrides)

    if resume_dir:
        # Override run config to point at existing run
        import dataclasses
        run_path = Path(resume_dir).resolve()
        config = dataclasses.replace(
            config,
            run=dataclasses.replace(
                config.run,
                scene_id=run_path.name,
                output_dir=str(run_path.parent),
                resume=True,
            ),
        )

    runner = PipelineRunner(config)

    try:
        output_path = runner.run()
        click.echo(f"\nDone! Output at: {output_path}")
        click.echo(f"  PLY:      {output_path / 'scene.ply'}")
        click.echo(f"  Manifest: {output_path / 'manifest.json'}")
    except PipelineError as e:
        click.echo(f"\nPipeline error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option("--run-dir", type=click.Path(exists=True), required=True,
              help="Path to an existing run directory.")
@click.option("--stage", type=click.Choice(["ingest", "sfm", "train", "export"]),
              required=True, help="Stage to run.")
@click.option("--config", "config_path", type=click.Path(exists=True), default=None,
              help="Path to TOML config file (overrides run config).")
@click.option("--iterations", type=int, default=None,
              help="Override training iterations (for train stage).")
def stage(
    run_dir: str,
    stage: str,
    config_path: str | None,
    iterations: int | None,
) -> None:
    """Run a single pipeline stage on an existing run directory."""
    import dataclasses

    overrides: dict = {}
    if iterations:
        overrides["train.iterations"] = iterations

    config_file = Path(config_path) if config_path else None
    config = load_config(config_file, overrides)

    run_path = Path(run_dir).resolve()
    config = dataclasses.replace(
        config,
        run=dataclasses.replace(
            config.run,
            scene_id=run_path.name,
            output_dir=str(run_path.parent),
        ),
    )

    runner = PipelineRunner(config)

    try:
        report = runner.run_stage(stage)
        click.echo(f"\nStage '{stage}' complete.")
    except PipelineError as e:
        click.echo(f"\nStage '{stage}' failed: {e}", err=True)
        sys.exit(1)


@cli.command()
def info() -> None:
    """Show pipeline version, GPU info, and tool availability."""
    from . import __version__
    click.echo(f"SplatAgent Pipeline v{__version__}")
    click.echo()

    # Python
    click.echo(f"Python: {sys.version}")
    click.echo()

    # PyTorch + CUDA
    try:
        import torch
        click.echo(f"PyTorch: {torch.__version__}")
        if torch.cuda.is_available():
            click.echo(f"CUDA: {torch.version.cuda}")
            click.echo(f"GPU: {torch.cuda.get_device_name(0)}")
            mem = torch.cuda.get_device_properties(0).total_mem / 1024**3
            click.echo(f"GPU Memory: {mem:.1f} GB")
        else:
            click.echo("CUDA: not available")
    except ImportError:
        click.echo("PyTorch: not installed")

    click.echo()

    # gsplat
    try:
        import gsplat
        click.echo(f"gsplat: {getattr(gsplat, '__version__', 'installed')}")
    except ImportError:
        click.echo("gsplat: not installed")

    # COLMAP
    import shutil
    import subprocess
    colmap = shutil.which("colmap")
    if colmap:
        click.echo(f"COLMAP: {colmap}")
    else:
        click.echo("COLMAP: not found")

    # ffmpeg
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        click.echo(f"ffmpeg: {ffmpeg}")
    else:
        click.echo("ffmpeg: not found")


@cli.command()
@click.option("--config", "config_path", type=click.Path(exists=True), required=True,
              help="Path to TOML config file to validate.")
def validate(config_path: str) -> None:
    """Validate a config file without running the pipeline."""
    try:
        config = load_config(Path(config_path))
        click.echo("Config is valid.")
        import json
        from .config import config_to_dict
        click.echo(json.dumps(config_to_dict(config), indent=2))
    except Exception as e:
        click.echo(f"Config error: {e}", err=True)
        sys.exit(1)
