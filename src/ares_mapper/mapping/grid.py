"""Regular world-aligned grid definition."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ares_mapper.config import BoundsConfig


@dataclass(frozen=True, slots=True)
class GridSpec:
    x_coordinates_m: np.ndarray
    y_coordinates_m: np.ndarray

    @classmethod
    def from_bounds(cls, bounds: BoundsConfig, resolution_m: float) -> GridSpec:
        if resolution_m <= 0:
            raise ValueError("grid resolution must be positive")
        x = np.arange(bounds.x_min, bounds.x_max + resolution_m * 0.5, resolution_m)
        y = np.arange(bounds.y_min, bounds.y_max + resolution_m * 0.5, resolution_m)
        return cls(x.astype(float), y.astype(float))

    @property
    def shape(self) -> tuple[int, int]:
        return (len(self.y_coordinates_m), len(self.x_coordinates_m))

    def points(self) -> np.ndarray:
        xx, yy = np.meshgrid(self.x_coordinates_m, self.y_coordinates_m)
        return np.column_stack((xx.ravel(), yy.ravel()))
