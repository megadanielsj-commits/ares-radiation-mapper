"""Small reusable validation helpers."""

from __future__ import annotations

import math


def clamp_probability(value: float) -> float:
    if not 0.0 <= value <= 1.0:
        raise ValueError("probability must be between 0 and 1")
    return value


def normalize_yaw(angle_rad: float) -> float:
    return math.atan2(math.sin(angle_rad), math.cos(angle_rad))
