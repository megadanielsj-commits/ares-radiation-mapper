"""Simulation-only comparison against the known ground-truth field."""

from __future__ import annotations

import math

import numpy as np


def map_metrics(
    estimated: np.ndarray,
    truth: np.ndarray,
    coverage: np.ndarray,
    x_coordinates: np.ndarray,
    y_coordinates: np.ndarray,
) -> dict[str, float | int | None]:
    valid = coverage & np.isfinite(estimated) & np.isfinite(truth)
    coverage_percent = float(100.0 * np.mean(coverage)) if coverage.size else 0.0
    if not np.any(valid):
        return {
            "mae_uSv_h": None,
            "rmse_uSv_h": None,
            "max_abs_error_uSv_h": None,
            "bias_uSv_h": None,
            "correlation": None,
            "hotspot_error_m": None,
            "coverage_percent": coverage_percent,
        }
    residual = estimated[valid] - truth[valid]
    correlation: float | None
    if np.std(estimated[valid]) > 0 and np.std(truth[valid]) > 0:
        correlation = float(np.corrcoef(estimated[valid], truth[valid])[0, 1])
    else:
        correlation = None
    estimated_masked = np.where(valid, estimated, -np.inf)
    truth_masked = np.where(valid, truth, -np.inf)
    estimated_index = np.unravel_index(int(np.argmax(estimated_masked)), estimated.shape)
    truth_index = np.unravel_index(int(np.argmax(truth_masked)), truth.shape)
    hotspot_error = math.dist(
        (
            float(x_coordinates[estimated_index[1]]),
            float(y_coordinates[estimated_index[0]]),
        ),
        (
            float(x_coordinates[truth_index[1]]),
            float(y_coordinates[truth_index[0]]),
        ),
    )
    return {
        "mae_uSv_h": float(np.mean(np.abs(residual))),
        "rmse_uSv_h": float(np.sqrt(np.mean(residual**2))),
        "max_abs_error_uSv_h": float(np.max(np.abs(residual))),
        "bias_uSv_h": float(np.mean(residual)),
        "correlation": correlation,
        "hotspot_error_m": float(hotspot_error),
        "coverage_percent": coverage_percent,
    }
