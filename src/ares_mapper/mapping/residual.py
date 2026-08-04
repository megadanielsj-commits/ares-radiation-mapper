"""Local-only IDW correction for deviations from the point-source model."""

from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree

from ares_mapper.config import ResidualConfig


class ResidualIDW:
    def __init__(self, config: ResidualConfig, observation_cell_m: float) -> None:
        self.config = config
        self.observation_cell_m = observation_cell_m

    def predict(
        self,
        query_points: np.ndarray,
        support_points: np.ndarray,
        support_residuals: np.ndarray,
        support_variances: np.ndarray,
        query_cell_sizes: np.ndarray | None = None,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        # Residual support is a property of the observations, not of the
        # quadtree leaf being queried.  Letting a coarse render cell enlarge
        # this radius made one new measurement alter several metres of map.
        del query_cell_sizes
        count = len(query_points)
        if len(support_points) == 0:
            return (
                np.zeros(count, dtype=float),
                np.full(count, 0.05**2, dtype=float),
                np.full(count, np.inf, dtype=float),
            )
        neighbors = min(self.config.neighbors, len(support_points))
        tree = cKDTree(support_points)
        distances, indexes = tree.query(query_points, k=neighbors)
        if neighbors == 1:
            distances = distances[:, None]
            indexes = indexes[:, None]
        support_radius = max(
            self.observation_cell_m,
            self.config.maximum_support_cells * self.observation_cell_m,
        )
        means = np.zeros(count, dtype=float)
        # Outside compact support there is no residual correction.  Physical
        # posterior uncertainty is already propagated separately.
        variances = np.zeros(count, dtype=float)
        nearest = distances[:, 0].copy()
        for row in range(count):
            valid = distances[row] < support_radius
            if not np.any(valid):
                continue
            local_distances = distances[row, valid]
            local_indexes = indexes[row, valid]
            if local_distances[0] <= 1e-9:
                means[row] = support_residuals[local_indexes[0]]
                variances[row] = support_variances[local_indexes[0]]
                continue
            normalized_distance = np.clip(
                local_distances / support_radius,
                0.0,
                1.0,
            )
            compact_taper = (1.0 - normalized_distance**2) ** 2
            weights = (
                compact_taper
                / np.maximum(
                    local_distances,
                    1e-6,
                )
                ** self.config.power
            )
            weights /= np.sum(weights)
            values = support_residuals[local_indexes]
            means[row] = float(np.sum(weights * values))
            spatial_variance = float(np.sum(weights * (values - means[row]) ** 2))
            variances[row] = float(
                np.sum(weights * support_variances[local_indexes]) + spatial_variance
            )
        return means, np.maximum(variances, 1e-10), nearest
