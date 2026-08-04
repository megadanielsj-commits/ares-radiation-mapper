"""FS-5000-inspired simulated detector response."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

import numpy as np

from ares_mapper.config import DetectorConfig
from ares_mapper.domain.enums import Quality


@dataclass(frozen=True, slots=True)
class DetectorReading:
    dose_rate_uSv_h: float
    cumulative_dose_uSv: float
    cps: int
    cpm: int
    average_dose_rate_uSv_h: float
    quality: Quality
    alarm: bool


class DetectorModel:
    def __init__(self, config: DetectorConfig, rng: np.random.Generator) -> None:
        self.config = config
        self.rng = rng
        self._response_uSv_h: float | None = None
        self._cumulative_uSv = 0.0
        self._average_sum = 0.0
        self._sample_count = 0
        self._cps_window: deque[int] = deque(maxlen=60)

    def measure(self, true_rate_uSv_h: float, delta_t_s: float) -> DetectorReading:
        true_rate = max(0.0, true_rate_uSv_h)
        if self._response_uSv_h is None:
            self._response_uSv_h = true_rate
        tau = max(self.config.response_time_constant_s, 1e-9)
        alpha = 1.0 - math.exp(-delta_t_s / tau)
        self._response_uSv_h += alpha * (true_rate - self._response_uSv_h)
        noisy = self._response_uSv_h
        noisy *= 1.0 + float(self.rng.normal(0.0, self.config.multiplicative_noise_fraction))
        noisy += float(self.rng.normal(0.0, self.config.additive_noise_std_uSv_h))
        noisy = max(0.0, noisy)

        sensitivity = float(
            self.config.sensitivity_cps_per_uSv_h or self.config.cpm_per_uSv_h / 60.0
        )
        cps = int(self.rng.poisson(noisy * sensitivity * delta_t_s))
        self._cps_window.append(cps)
        observed_window_s = max(delta_t_s * len(self._cps_window), delta_t_s)
        cpm = int(round(sum(self._cps_window) * 60.0 / observed_window_s))
        if self.config.response_mode == "counts_derived":
            measured = cpm / self.config.cpm_per_uSv_h
        else:
            measured = noisy
        quantum = self.config.dose_rate_quantization_uSv_h
        if quantum > 0:
            measured = round(measured / quantum) * quantum
        quality = Quality.VALID
        if self.rng.random() < self.config.outlier_probability:
            measured *= self.config.outlier_multiplier
            quality = Quality.DEGRADED
        measured = max(0.0, measured)
        self._cumulative_uSv += measured * delta_t_s / 3600.0
        cumulative_quantum = self.config.cumulative_quantization_uSv
        displayed_cumulative = (
            round(self._cumulative_uSv / cumulative_quantum) * cumulative_quantum
            if cumulative_quantum > 0
            else self._cumulative_uSv
        )
        self._sample_count += 1
        self._average_sum += measured
        average = self._average_sum / self._sample_count
        alarm = (
            self.config.alarm_threshold_uSv_h is not None
            and measured >= self.config.alarm_threshold_uSv_h
        )
        return DetectorReading(
            measured,
            max(0.0, displayed_cumulative),
            cps,
            cpm,
            average,
            quality,
            alarm,
        )
