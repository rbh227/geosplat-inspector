"""Metrics schema (ARCHITECTURE.md §6.4). Frozen."""

from __future__ import annotations

from typing import TypedDict


class OpacityMetrics(TypedDict):
    histogram: list[int]
    nearTransparentFraction: float
    mean: float
    median: float


class AxisRatioMetrics(TypedDict):
    histogram: list[int]
    needleFraction: float


class ScaleMetrics(TypedDict):
    histogram: list[int]
    oversizedFraction: float
    axisRatio: AxisRatioMetrics


class NNDistanceMetrics(TypedDict):
    mean: float
    std: float
    histogram: list[int]


class SpatialMetrics(TypedDict):
    nnDistance: NNDistanceMetrics
    outlierFraction: float
    density: float


class BoundsMetrics(TypedDict):
    min: list[float]  # [x, y, z]
    max: list[float]  # [x, y, z]
    volume: float


class ColorMetrics(TypedDict):
    dcMean: list[float]  # [r, g, b]
    dcStd: list[float]   # [r, g, b]


class Metrics(TypedDict):
    gaussianCount: int
    opacity: OpacityMetrics
    scale: ScaleMetrics
    spatial: SpatialMetrics
    bounds: BoundsMetrics
    color: ColorMetrics
    computedAt: str
    region: dict | None
