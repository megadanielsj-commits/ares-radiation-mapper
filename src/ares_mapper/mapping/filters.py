"""Declared filters that preserve the raw measurement."""

from __future__ import annotations

from collections import defaultdict, deque

import numpy as np

from ares_mapper.config import FilterConfig
from ares_mapper.domain.models import MappedSample


class SampleFilter:
    def __init__(self, config: FilterConfig) -> None:
        self.config = config
        self._ema: dict[str, float] = {}
        self._windows: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=max(1, config.window))
        )

    def apply(self, sample: MappedSample) -> MappedSample:
        raw = sample.dose_rate_uSv_h_raw
        if self.config.type == "ema":
            previous = self._ema.get(sample.sensor_id, raw)
            filtered = self.config.alpha * raw + (1.0 - self.config.alpha) * previous
            self._ema[sample.sensor_id] = filtered
        elif self.config.type == "median":
            window = self._windows[sample.sensor_id]
            window.append(raw)
            filtered = float(np.median(window))
        else:
            filtered = raw
        return sample.model_copy(update={"dose_rate_uSv_h_filtered": filtered})
