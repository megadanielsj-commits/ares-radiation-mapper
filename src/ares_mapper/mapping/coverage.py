"""Coverage mask rules that prevent unbounded extrapolation."""

from __future__ import annotations

import numpy as np
from scipy.spatial import Delaunay, QhullError, cKDTree


def coverage_mask(
    grid_points: np.ndarray,
    sample_points: np.ndarray,
    influence_radius_m: float,
    minimum_neighbors: int,
    mode: str,
) -> np.ndarray:
    if sample_points.size == 0:
        return np.zeros(len(grid_points), dtype=bool)
    tree = cKDTree(sample_points)
    neighbors = tree.query_ball_point(grid_points, influence_radius_m)
    mask = np.fromiter(
        (len(indices) >= minimum_neighbors for indices in neighbors),
        dtype=bool,
        count=len(grid_points),
    )
    if mode == "radius_and_convex_hull" and len(sample_points) >= 3:
        unique = np.unique(sample_points, axis=0)
        if len(unique) >= 3:
            try:
                hull = Delaunay(unique)
                mask &= hull.find_simplex(grid_points) >= 0
            except QhullError:
                pass
    return mask
