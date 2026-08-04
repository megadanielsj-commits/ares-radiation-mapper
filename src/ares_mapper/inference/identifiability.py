"""Geometry and model-consistency diagnostics for source localization."""

from __future__ import annotations

import math
from collections import deque

import numpy as np

from ares_mapper.config import InferenceConfig
from ares_mapper.domain.enums import IdentifiabilityState
from ares_mapper.domain.models import ObservationWindow


class IdentifiabilityMonitor:
    def __init__(self, config: InferenceConfig, cell_size_m: float = 1.0) -> None:
        self.config = config
        self.cell_size_m = cell_size_m
        self._positions: deque[tuple[float, float]] = deque(maxlen=512)
        self._independent_cells: set[tuple[int, int]] = set()
        self._standardized_residuals: deque[float] = deque(maxlen=128)

    def add(self, window: ObservationWindow, standardized_residual: float) -> None:
        x_m, y_m, _ = window.representative_xyz
        self._positions.append((x_m, y_m))
        self._independent_cells.add(
            (
                math.floor(x_m / self.cell_size_m),
                math.floor(y_m / self.cell_size_m),
            )
        )
        if math.isfinite(standardized_residual):
            self._standardized_residuals.append(standardized_residual)

    def evaluate(
        self,
        particles_xy: np.ndarray,
        weights: np.ndarray,
        posterior_center: tuple[float, float],
        radius_95_m: float,
        p_source_exists: float,
    ) -> tuple[IdentifiabilityState, dict[str, float | int | bool]]:
        geometry = self.geometry_metrics(posterior_center)
        entropy = self.position_entropy(particles_xy, weights)
        multimodal = self._is_multimodal(particles_xy, weights)
        mismatch = self._model_mismatch()
        if mismatch:
            state = IdentifiabilityState.MODEL_MISMATCH
        elif (
            len(self._independent_cells) < self.config.minimum_independent_cells
            or geometry["spatial_span_m"] < self.config.minimum_spatial_span_m
        ):
            state = IdentifiabilityState.INSUFFICIENT
        elif multimodal:
            state = IdentifiabilityState.MULTIMODAL
        elif (
            p_source_exists >= self.config.source_exists_threshold
            and radius_95_m <= self.config.stable_radius_95_m
            and geometry["angular_coverage_deg"] >= 90.0
        ):
            state = IdentifiabilityState.STABLE
        else:
            state = IdentifiabilityState.CONVERGING
        return state, {
            **geometry,
            "position_entropy": entropy,
            "independent_cell_count": len(self._independent_cells),
            "multimodal": multimodal,
            "model_mismatch": mismatch,
            "standardized_residual_rms": self._residual_rms(),
        }

    def geometry_metrics(self, posterior_center: tuple[float, float]) -> dict[str, float]:
        if not self._positions:
            return {
                "spatial_span_m": 0.0,
                "angular_coverage_deg": 0.0,
                "geometry_condition": float("inf"),
            }
        positions = np.asarray(self._positions, dtype=float)
        span = float(np.linalg.norm(np.ptp(positions, axis=0)))
        if len(positions) < 2:
            condition = float("inf")
        else:
            covariance = np.cov(positions.T)
            eigenvalues = np.linalg.eigvalsh(np.atleast_2d(covariance))
            condition = float(max(eigenvalues) / max(float(min(eigenvalues)), 1e-12))
        relative = positions - np.asarray(posterior_center, dtype=float)
        angles = np.unique(np.mod(np.arctan2(relative[:, 1], relative[:, 0]), 2 * math.pi))
        if len(angles) < 2:
            coverage_deg = 0.0
        else:
            wrapped = np.concatenate([angles, angles[:1] + 2 * math.pi])
            largest_gap = float(np.max(np.diff(wrapped)))
            coverage_deg = math.degrees(2 * math.pi - largest_gap)
        return {
            "spatial_span_m": span,
            "angular_coverage_deg": coverage_deg,
            "geometry_condition": condition,
        }

    @staticmethod
    def position_entropy(particles_xy: np.ndarray, weights: np.ndarray) -> float:
        if len(particles_xy) == 0:
            return 0.0
        histogram, _, _ = np.histogram2d(
            particles_xy[:, 0],
            particles_xy[:, 1],
            bins=24,
            weights=weights,
        )
        probabilities = histogram[histogram > 0]
        return float(-np.sum(probabilities * np.log(probabilities)))

    @staticmethod
    def _is_multimodal(particles_xy: np.ndarray, weights: np.ndarray) -> bool:
        if len(particles_xy) < 8:
            return False
        histogram, _, _ = np.histogram2d(
            particles_xy[:, 0],
            particles_xy[:, 1],
            bins=16,
            weights=weights,
        )
        if float(np.max(histogram)) <= 0:
            return False
        padded = np.pad(histogram, 1, mode="constant")
        peaks: list[tuple[float, int, int]] = []
        for x_index in range(histogram.shape[0]):
            for y_index in range(histogram.shape[1]):
                value = float(histogram[x_index, y_index])
                neighborhood = padded[
                    x_index : x_index + 3,
                    y_index : y_index + 3,
                ]
                if value > 0.0 and value >= float(np.max(neighborhood)):
                    peaks.append((value, x_index, y_index))
        if len(peaks) < 2:
            return False
        peaks.sort(reverse=True)
        leading = peaks[0]
        for candidate in peaks[1:]:
            separation = math.hypot(
                candidate[1] - leading[1],
                candidate[2] - leading[2],
            )
            if separation >= 3.0 and candidate[0] >= 0.55 * leading[0] and candidate[0] >= 0.04:
                return True
        return False

    def _residual_rms(self) -> float:
        if not self._standardized_residuals:
            return 0.0
        residuals = np.asarray(self._standardized_residuals, dtype=float)
        return float(np.sqrt(np.mean(residuals * residuals)))

    def _model_mismatch(self) -> bool:
        return (
            len(self._standardized_residuals) >= 10
            and self._residual_rms() > self.config.mismatch_normalized_rmse
        )
