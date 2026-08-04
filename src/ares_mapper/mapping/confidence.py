"""Empirical calibration hook for nominal posterior intervals."""

from __future__ import annotations


class ConfidenceCalibrator:
    """Stores an interval inflation factor derived from held-out coverage."""

    def __init__(self, inflation_factor: float = 1.0) -> None:
        self.inflation_factor = max(1.0, inflation_factor)

    def calibrate(self, nominal: float, observed: float) -> float:
        if observed <= 0:
            self.inflation_factor = max(self.inflation_factor, 2.0)
        elif observed < nominal:
            self.inflation_factor = max(
                self.inflation_factor,
                min(3.0, (nominal / observed) ** 0.5),
            )
        return self.inflation_factor

    def interval(self, median: float, lower: float, upper: float) -> tuple[float, float]:
        return (
            max(0.0, median - (median - lower) * self.inflation_factor),
            median + (upper - median) * self.inflation_factor,
        )
