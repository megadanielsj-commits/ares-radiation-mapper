"""Inverse-distance and Gaussian-kernel interpolation."""

from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree


def interpolate(
    grid_points: np.ndarray,
    sample_points: np.ndarray,
    sample_values: np.ndarray,
    sample_times_ns: np.ndarray,
    *,
    at_time_ns: int,
    power: float,
    epsilon_m: float,
    influence_radius_m: float,
    maximum_neighbors: int,
    method: str = "idw",
    time_decay_tau_s: float | None = None,
) -> np.ndarray:
    if sample_points.size == 0:
        return np.full(len(grid_points), np.nan, dtype=float)
    neighbor_count = min(maximum_neighbors, len(sample_points))
    tree = cKDTree(sample_points)
    distances, indices = tree.query(
        grid_points,
        k=neighbor_count,
        distance_upper_bound=influence_radius_m,
    )
    if neighbor_count == 1:
        distances = distances[:, None]
        indices = indices[:, None]
    valid = np.isfinite(distances) & (indices < len(sample_values))
    safe_indices = np.where(valid, indices, 0)
    if method == "gaussian":
        scale = max(influence_radius_m / 2.0, epsilon_m)
        weights = np.exp(-((distances / scale) ** 2))
    else:
        weights = 1.0 / np.power(distances + epsilon_m, power)
    weights = np.where(valid, weights, 0.0)
    if time_decay_tau_s is not None and time_decay_tau_s > 0:
        ages_s = np.abs(at_time_ns - sample_times_ns[safe_indices]) / 1_000_000_000
        weights *= np.exp(-ages_s / time_decay_tau_s)
    weighted_values = weights * sample_values[safe_indices]
    denominator = np.sum(weights, axis=1)
    result = np.divide(
        np.sum(weighted_values, axis=1),
        denominator,
        out=np.full(len(grid_points), np.nan, dtype=float),
        where=denominator > 0,
    )
    neighbor_values = sample_values[safe_indices]
    minimum = np.min(np.where(valid, neighbor_values, np.inf), axis=1)
    maximum = np.max(np.where(valid, neighbor_values, -np.inf), axis=1)
    rows_with_neighbors = denominator > 0
    result[rows_with_neighbors] = np.clip(
        result[rows_with_neighbors],
        minimum[rows_with_neighbors],
        maximum[rows_with_neighbors],
    )

    # Exact coincident observations take their arithmetic mean.
    exact = valid & (distances <= 1e-12)
    exact_rows = np.flatnonzero(np.any(exact, axis=1))
    for row in exact_rows:
        result[row] = float(np.mean(sample_values[safe_indices[row, exact[row]]]))
    return result
