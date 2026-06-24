"""Structured logging with Rich console + file output."""

from __future__ import annotations

import logging
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

_console = Console(stderr=True)


def setup_logging(run_dir: Path | None = None, level: int = logging.INFO) -> logging.Logger:
    """Configure the pipeline logger with rich console output and optional file handler."""
    logger = logging.getLogger("splatagent_pipeline")
    logger.setLevel(level)

    # Avoid duplicate handlers on repeated calls
    if logger.handlers:
        return logger

    # Console handler with Rich formatting
    console_handler = RichHandler(
        console=_console,
        show_time=True,
        show_path=False,
        markup=True,
        rich_tracebacks=True,
    )
    console_handler.setLevel(level)
    logger.addHandler(console_handler)

    # File handler if run_dir is provided
    if run_dir is not None:
        run_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(run_dir / "pipeline.log")
        file_handler.setLevel(level)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
        )
        logger.addHandler(file_handler)

    return logger


def get_logger() -> logging.Logger:
    """Get the pipeline logger (must call setup_logging first)."""
    return logging.getLogger("splatagent_pipeline")
