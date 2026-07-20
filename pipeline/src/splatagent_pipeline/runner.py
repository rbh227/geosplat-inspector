"""Pipeline orchestrator — runs all stages in sequence with resumability."""

from __future__ import annotations

import dataclasses
import json
import uuid
from pathlib import Path

from .config import PipelineConfig, config_to_dict
from .logging_setup import get_logger, setup_logging


class PipelineError(Exception):
    pass


class PipelineRunner:
    """Orchestrates the four pipeline stages with per-run directories and resumability."""

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.scene_id = config.run.scene_id or str(uuid.uuid4())
        self.run_dir = Path(config.run.output_dir) / self.scene_id

    def run(self) -> Path:
        """Execute the full pipeline. Returns path to output directory."""
        self.run_dir.mkdir(parents=True, exist_ok=True)

        # Setup logging to run directory
        log = setup_logging(self.run_dir)
        log.info(f"Pipeline run: scene_id={self.scene_id}")
        log.info(f"Run directory: {self.run_dir}")

        # Save frozen config snapshot
        self._save_config_snapshot()

        # Each stage imported individually — train/export need torch
        self.run_stage("ingest")
        self.run_stage("sfm")
        self.run_stage("train")
        self.run_stage("export")

        log.info(f"[bold green]Pipeline complete! Output: {self.run_dir / 'output'}[/]")
        return self.run_dir / "output"

    def run_stage(self, stage_name: str) -> dict:
        """Run a single stage by name. Returns the stage report.

        Imports each stage lazily so train/export don't require torch
        just to run ingest or sfm.
        """
        self.run_dir.mkdir(parents=True, exist_ok=True)
        setup_logging(self.run_dir)

        if stage_name == "ingest":
            from .stages import ingest
            try:
                return ingest.run_ingest(self.config, self.run_dir)
            except ingest.IngestError as e:
                raise PipelineError(f"Ingestion failed: {e}") from e

        elif stage_name == "sfm":
            from .stages import sfm
            try:
                return sfm.run_sfm(self.config, self.run_dir)
            except sfm.SfMError as e:
                raise PipelineError(f"SfM failed: {e}") from e

        elif stage_name == "train":
            from .stages import train
            try:
                return train.run_train(self.config, self.run_dir)
            except train.TrainError as e:
                raise PipelineError(f"Training failed: {e}") from e

        elif stage_name == "export":
            from .stages import export
            try:
                return export.run_export(self.config, self.run_dir, self.scene_id)
            except export.ExportError as e:
                raise PipelineError(f"Export failed: {e}") from e

        else:
            raise PipelineError(
                f"Unknown stage: {stage_name}. Valid: ingest, sfm, train, export"
            )

    def _save_config_snapshot(self) -> None:
        """Save the current config as JSON in the run directory."""
        snapshot_path = self.run_dir / "config_snapshot.json"
        if not snapshot_path.exists():
            with open(snapshot_path, "w") as f:
                json.dump(config_to_dict(self.config), f, indent=2)
