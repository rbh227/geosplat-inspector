"""Fixtures for the analysis tests.

Acceptance scenes are the frozen Phase-0 examples (loaded via Agent 1's real
``GaussianSplatModel``). A synthetic model with nonzero f_rest / varied attributes
exercises the attribute-edit revert paths that the all-zero example scenes can't.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from backend.splat.model import GaussianSplatModel

EXAMPLES = Path(__file__).resolve().parents[3] / "examples"


@pytest.fixture
def clean_model() -> GaussianSplatModel:
    return GaussianSplatModel.load(str(EXAMPLES / "clean.ply"))


@pytest.fixture
def messy_model() -> GaussianSplatModel:
    return GaussianSplatModel.load(str(EXAMPLES / "messy.ply"))


@pytest.fixture
def synth_model() -> GaussianSplatModel:
    """A small random scene with nonzero SH rest and spread-out attributes."""
    rng = np.random.default_rng(7)
    n = 400
    means = rng.normal(0, 1, (n, 3)).astype(np.float32)
    scales_raw = rng.normal(-4.0, 0.3, (n, 3)).astype(np.float32)
    quats = np.tile(np.array([1, 0, 0, 0], np.float32), (n, 1))
    opacity_raw = rng.normal(1.5, 1.0, n).astype(np.float32)
    f_dc = rng.normal(0, 1, (n, 3)).astype(np.float32)
    f_rest = rng.normal(0, 0.5, (n, 45)).astype(np.float32)  # degree 3, nonzero
    return GaussianSplatModel(
        means=means, scales_raw=scales_raw, quats=quats,
        opacity_raw=opacity_raw, f_dc=f_dc, f_rest=f_rest, sh_degree=3,
    )
