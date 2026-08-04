"""Configurable odometry degradation."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ares_mapper.config import OdometryConfig
from ares_mapper.domain.enums import Quality
from ares_mapper.domain.validation import normalize_yaw
from ares_mapper.simulation.trajectory import GroundTruthPose


@dataclass(frozen=True, slots=True)
class OdometryMeasurement:
    x_m: float
    y_m: float
    z_m: float
    yaw_rad: float
    quality: Quality
    position_std_m: float
    yaw_std_rad: float


class OdometryModel:
    def __init__(self, config: OdometryConfig, rng: np.random.Generator) -> None:
        self.config = config
        self.rng = rng

    def measure(self, truth: GroundTruthPose, time_s: float) -> OdometryMeasurement:
        drift_total = self.config.drift_m_per_min * time_s / 60.0
        x = truth.x_m + self.config.bias_x_m + drift_total / math.sqrt(2)
        y = truth.y_m + self.config.bias_y_m - drift_total / math.sqrt(2)
        yaw = truth.yaw_rad + self.config.yaw_drift_rad_per_min * time_s / 60.0
        x += float(self.rng.normal(0.0, self.config.position_noise_std_m))
        y += float(self.rng.normal(0.0, self.config.position_noise_std_m))
        yaw += float(self.rng.normal(0.0, self.config.yaw_noise_std_rad))
        quality = Quality.VALID
        if self.rng.random() < self.config.outlier_probability:
            x += float(self.rng.normal(0.0, self.config.outlier_position_std_m))
            y += float(self.rng.normal(0.0, self.config.outlier_position_std_m))
            quality = Quality.DEGRADED
        return OdometryMeasurement(
            x,
            y,
            truth.z_m,
            normalize_yaw(yaw),
            quality,
            self.config.position_noise_std_m,
            self.config.yaw_noise_std_rad,
        )
