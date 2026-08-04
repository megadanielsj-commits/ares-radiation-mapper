"""Fixed-resolution sufficient statistics for measured support and residuals."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ares_mapper.config import BoundsConfig
from ares_mapper.domain.enums import EvidenceKind, Quality
from ares_mapper.domain.models import ObservationWindow


@dataclass(slots=True)
class ObservationCellStats:
    weighted_time_s: float = 0.0
    weighted_value_sum: float = 0.0
    weighted_value_sq_sum: float = 0.0
    weighted_residual_sum: float = 0.0
    weighted_residual_sq_sum: float = 0.0
    weighted_measurement_variance_sum: float = 0.0
    effective_observations: float = 0.0
    last_update_ns: int = 0
    quality_sum: float = 0.0
    exposure_uSv: float = 0.0
    maximum_pose_std_m: float = 0.0
    maximum_speed_m_s: float = 0.0

    @property
    def mean_rate(self) -> float:
        return self.weighted_value_sum / max(self.weighted_time_s, 1e-12)

    @property
    def value_variance(self) -> float:
        mean = self.mean_rate
        return max(
            0.0,
            self.weighted_value_sq_sum / max(self.weighted_time_s, 1e-12) - mean * mean,
        )

    @property
    def residual_mean(self) -> float:
        return self.weighted_residual_sum / max(self.weighted_time_s, 1e-12)

    @property
    def residual_variance(self) -> float:
        mean = self.residual_mean
        return max(
            0.0,
            self.weighted_residual_sq_sum / max(self.weighted_time_s, 1e-12) - mean * mean,
        )

    @property
    def mean_measurement_variance(self) -> float:
        return self.weighted_measurement_variance_sum / max(
            self.weighted_time_s,
            1e-12,
        )


class ObservationGrid:
    """Aggregates raw observations without depending on render resolution."""

    def __init__(self, bounds: BoundsConfig, cell_size_m: float) -> None:
        self.bounds = bounds
        self.cell_size_m = cell_size_m
        self.cells: dict[tuple[int, int], ObservationCellStats] = {}
        self.raw_observation_count = 0
        self.total_weighted_time_s = 0.0

    def add(
        self,
        window: ObservationWindow,
        observed_rate_uSv_h: float,
        physical_rate_uSv_h: float,
        measurement_std_uSv_h: float = 0.0,
    ) -> None:
        quality = 1.0 if window.quality == Quality.VALID else 0.45
        if window.evidence_kind == EvidenceKind.CUMULATIVE_RECOVERY:
            quality *= 0.25
        quality /= 1.0 + (window.sync_error_ms / 250.0) ** 2
        speed = self._path_speed(window)
        residual = observed_rate_uSv_h - physical_rate_uSv_h
        for point, path_weight_s in zip(
            window.detector_path, window.path_time_weights_s, strict=True
        ):
            if path_weight_s <= 0:
                continue
            key = self.key(point.x_m, point.y_m)
            if key is None:
                continue
            weighted_time = path_weight_s * quality
            stats = self.cells.setdefault(key, ObservationCellStats())
            stats.weighted_time_s += weighted_time
            stats.weighted_value_sum += observed_rate_uSv_h * weighted_time
            stats.weighted_value_sq_sum += observed_rate_uSv_h**2 * weighted_time
            stats.weighted_residual_sum += residual * weighted_time
            stats.weighted_residual_sq_sum += residual**2 * weighted_time
            stats.weighted_measurement_variance_sum += (
                max(0.0, measurement_std_uSv_h) ** 2 * weighted_time
            )
            stats.effective_observations += (
                path_weight_s / max(window.integration_time_s, 1e-12)
            ) * quality
            stats.last_update_ns = max(stats.last_update_ns, window.integration_end_ns)
            stats.quality_sum += quality
            stats.exposure_uSv += observed_rate_uSv_h * path_weight_s / 3600.0
            stats.maximum_pose_std_m = max(stats.maximum_pose_std_m, point.position_std_m)
            stats.maximum_speed_m_s = max(stats.maximum_speed_m_s, speed)
            self.total_weighted_time_s += weighted_time
        self.raw_observation_count += 1

    def key(self, x_m: float, y_m: float) -> tuple[int, int] | None:
        if not (
            self.bounds.x_min <= x_m <= self.bounds.x_max
            and self.bounds.y_min <= y_m <= self.bounds.y_max
        ):
            return None
        x_index = int(math.floor((x_m - self.bounds.x_min) / self.cell_size_m))
        y_index = int(math.floor((y_m - self.bounds.y_min) / self.cell_size_m))
        maximum_x_index = max(
            0,
            int(math.ceil((self.bounds.x_max - self.bounds.x_min) / self.cell_size_m)) - 1,
        )
        maximum_y_index = max(
            0,
            int(math.ceil((self.bounds.y_max - self.bounds.y_min) / self.cell_size_m)) - 1,
        )
        return (
            min(x_index, maximum_x_index),
            min(y_index, maximum_y_index),
        )

    def center(self, key: tuple[int, int]) -> tuple[float, float]:
        return (
            self.bounds.x_min + (key[0] + 0.5) * self.cell_size_m,
            self.bounds.y_min + (key[1] + 0.5) * self.cell_size_m,
        )

    def support_arrays(
        self,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        if not self.cells:
            empty = np.empty((0,), dtype=float)
            return np.empty((0, 2), dtype=float), empty, empty, empty
        keys = list(self.cells)
        points = np.asarray([self.center(key) for key in keys], dtype=float)
        rates = np.asarray([self.cells[key].mean_rate for key in keys], dtype=float)
        variances = np.asarray(
            [
                (self.cells[key].value_variance + self.cells[key].mean_measurement_variance)
                / max(self.cells[key].effective_observations, 1.0)
                for key in keys
            ],
            dtype=float,
        )
        coverage = np.asarray([self.cells[key].weighted_time_s for key in keys], dtype=float)
        return points, rates, variances, coverage

    def query_stats(
        self, points_xy: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        coverage = np.zeros(len(points_xy), dtype=float)
        observations = np.zeros(len(points_xy), dtype=float)
        exposure = np.zeros(len(points_xy), dtype=float)
        last_update = np.zeros(len(points_xy), dtype=np.int64)
        for index, (x_m, y_m) in enumerate(points_xy):
            key = self.key(float(x_m), float(y_m))
            if key is None or key not in self.cells:
                continue
            stats = self.cells[key]
            coverage[index] = stats.weighted_time_s
            observations[index] = stats.effective_observations
            exposure[index] = stats.exposure_uSv
            last_update[index] = stats.last_update_ns
        return coverage, observations, exposure, last_update

    def maximum_pose_std_m(self) -> float:
        return max(
            (stats.maximum_pose_std_m for stats in self.cells.values()),
            default=0.0,
        )

    def speed_percentile(self, percentile: float = 95.0) -> float:
        values = [stats.maximum_speed_m_s for stats in self.cells.values()]
        return float(np.percentile(values, percentile)) if values else 0.0

    @staticmethod
    def _path_speed(window: ObservationWindow) -> float:
        if window.integration_time_s <= 0 or len(window.detector_path) < 2:
            return 0.0
        reported = [point.speed_m_s for point in window.detector_path if point.speed_m_s > 0]
        if reported:
            return float(np.percentile(reported, 95.0))
        first = window.detector_path[0]
        last = window.detector_path[-1]
        endpoint_speed = (
            math.dist(
                (first.x_m, first.y_m, first.z_m),
                (last.x_m, last.y_m, last.z_m),
            )
            / window.integration_time_s
        )
        if endpoint_speed > 0:
            return endpoint_speed
        distances = [
            math.dist(
                (previous.x_m, previous.y_m, previous.z_m),
                (current.x_m, current.y_m, current.z_m),
            )
            for previous, current in zip(
                window.detector_path,
                window.detector_path[1:],
                strict=False,
            )
        ]
        return sum(distances) / window.integration_time_s
