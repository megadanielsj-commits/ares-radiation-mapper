"""Radiological display scales and regulatory reference levels."""

from __future__ import annotations

import math
from dataclasses import dataclass

from ares_mapper.config import (
    IOE_INVESTIGATION_EQUIVALENT_RATE_USV_H,
    IOE_LIMIT_EQUIVALENT_RATE_USV_H,
    IOE_MAXIMUM_EQUIVALENT_RATE_USV_H,
    IOE_RECORDING_EQUIVALENT_RATE_USV_H,
    MAX_SIMULATION_SOURCE_STRENGTH_USV_H,
    PUBLIC_CONTINUOUS_REFERENCE_RATE_USV_H,
)

PUBLIC_REFERENCE_FRACTION = 0.06
DEFAULT_DISPLAY_DISTANCE_M = 0.5

# Original ARES heat-map palette used through V0.4.4.  The colours describe
# relative intensity inside the current mission; regulatory levels remain
# independent annotations and never force the whole high-rate field to red.
ARES_CLASSIC_COLOR_STOPS: tuple[tuple[float, tuple[int, int, int]], ...] = (
    (0.00, (11, 27, 42)),
    (0.16, (28, 87, 111)),
    (0.35, (57, 151, 145)),
    (0.54, (218, 195, 103)),
    (0.74, (230, 116, 71)),
    (1.00, (183, 35, 58)),
)


@dataclass(frozen=True)
class ScaleAnchor:
    rate_uSv_h: float
    fraction: float
    rgb: tuple[int, int, int]
    label: str | None = None

    @property
    def hex_color(self) -> str:
        return "#" + "".join(f"{channel:02x}" for channel in self.rgb)


def mission_scale_bounds(
    source_rate_uSv_h: float,
    *,
    background_rate_uSv_h: float,
    physical_minimum_distance_m: float,
    display_distance_m: float = DEFAULT_DISPLAY_DISTANCE_M,
) -> tuple[float, float]:
    """Return stable logarithmic colour bounds for one configured mission.

    The upper bound represents the configured source at the larger of the
    physical minimum distance and 0.5 m. Values closer than that may saturate,
    which reserves red for the most intense part of the reconstructed field.
    """

    if source_rate_uSv_h <= 0:
        raise ValueError("source rate must be positive")
    if background_rate_uSv_h < 0:
        raise ValueError("background rate cannot be negative")
    if physical_minimum_distance_m <= 0 or display_distance_m <= 0:
        raise ValueError("display distances must be positive")

    effective_distance = max(
        physical_minimum_distance_m,
        display_distance_m,
    )
    minimum = max(
        1e-6,
        (
            background_rate_uSv_h
            if background_rate_uSv_h > 0
            else max(source_rate_uSv_h / 1_000_000.0, 1e-3)
        ),
    )
    maximum = max(
        0.25,
        background_rate_uSv_h + source_rate_uSv_h / (effective_distance * effective_distance),
    )
    return minimum, max(maximum, minimum * 1.000001)


def logarithmic_scale_fraction(
    total_rate_uSv_h: float,
    *,
    minimum_rate_uSv_h: float,
    maximum_rate_uSv_h: float,
) -> float:
    """Map a total dose rate to a bounded mission-relative log fraction."""

    if minimum_rate_uSv_h <= 0:
        raise ValueError("minimum rate must be positive")
    if maximum_rate_uSv_h <= minimum_rate_uSv_h:
        raise ValueError("maximum rate must exceed minimum rate")
    value = min(
        max(float(total_rate_uSv_h), minimum_rate_uSv_h),
        maximum_rate_uSv_h,
    )
    return (math.log10(value) - math.log10(minimum_rate_uSv_h)) / (
        math.log10(maximum_rate_uSv_h) - math.log10(minimum_rate_uSv_h)
    )


def classic_scale_anchors(
    *,
    minimum_rate_uSv_h: float,
    maximum_rate_uSv_h: float,
) -> tuple[ScaleAnchor, ...]:
    """Return the original ARES palette anchored to mission-relative rates."""

    if minimum_rate_uSv_h <= 0:
        raise ValueError("minimum rate must be positive")
    if maximum_rate_uSv_h <= minimum_rate_uSv_h:
        raise ValueError("maximum rate must exceed minimum rate")
    log_minimum = math.log10(minimum_rate_uSv_h)
    log_width = math.log10(maximum_rate_uSv_h) - log_minimum
    return tuple(
        ScaleAnchor(
            rate_uSv_h=10 ** (log_minimum + fraction * log_width),
            fraction=fraction,
            rgb=rgb,
        )
        for fraction, rgb in ARES_CLASSIC_COLOR_STOPS
    )


def regulatory_scale_fraction(
    excess_rate_uSv_h: float,
    *,
    reference_rate_uSv_h: float = PUBLIC_CONTINUOUS_REFERENCE_RATE_USV_H,
    maximum_rate_uSv_h: float = MAX_SIMULATION_SOURCE_STRENGTH_USV_H,
) -> float:
    """Map source contribution to the fixed regulatory-reference scale.

    The range below the continuous public reference occupies six percent of
    the display. Values above it use logarithmic spacing through the maximum
    simulated source rate. Regulatory IOE levels are color anchors on this
    absolute mapping and do not change between missions.
    """

    if reference_rate_uSv_h <= 0:
        raise ValueError("reference rate must be positive")
    if maximum_rate_uSv_h <= reference_rate_uSv_h:
        raise ValueError("maximum rate must exceed the reference rate")
    value = min(max(float(excess_rate_uSv_h), 0.0), maximum_rate_uSv_h)
    if value <= reference_rate_uSv_h:
        return PUBLIC_REFERENCE_FRACTION * value / reference_rate_uSv_h
    logarithmic_fraction = math.log10(value / reference_rate_uSv_h) / math.log10(
        maximum_rate_uSv_h / reference_rate_uSv_h
    )
    return min(
        1.0,
        PUBLIC_REFERENCE_FRACTION + (1.0 - PUBLIC_REFERENCE_FRACTION) * logarithmic_fraction,
    )


def regulatory_scale_anchors(
    *,
    reference_rate_uSv_h: float = PUBLIC_CONTINUOUS_REFERENCE_RATE_USV_H,
    recording_rate_uSv_h: float = IOE_RECORDING_EQUIVALENT_RATE_USV_H,
    investigation_rate_uSv_h: float = IOE_INVESTIGATION_EQUIVALENT_RATE_USV_H,
    limit_rate_uSv_h: float = IOE_LIMIT_EQUIVALENT_RATE_USV_H,
    occupational_maximum_rate_uSv_h: float = IOE_MAXIMUM_EQUIVALENT_RATE_USV_H,
    maximum_rate_uSv_h: float = MAX_SIMULATION_SOURCE_STRENGTH_USV_H,
) -> tuple[ScaleAnchor, ...]:
    """Return the fixed public/IOE green-to-hottest-red scale anchors."""

    points = (
        (0.0, (8, 18, 27), None),
        (
            reference_rate_uSv_h,
            (43, 183, 94),
            "Público · 1 mSv/ano",
        ),
        (
            recording_rate_uSv_h,
            (139, 195, 74),
            "IOE registro · 1 mSv/ano",
        ),
        (
            investigation_rate_uSv_h,
            (243, 200, 57),
            "IOE investigação · 6 mSv/ano",
        ),
        (
            limit_rate_uSv_h,
            (239, 125, 43),
            "IOE limite · 20 mSv/ano",
        ),
        (
            occupational_maximum_rate_uSv_h,
            (220, 47, 54),
            "IOE teto · 50 mSv/ano",
        ),
        (1_000.0, (194, 24, 58), None),
        (100_000.0, (145, 17, 59), None),
        (maximum_rate_uSv_h, (92, 10, 45), None),
    )
    anchors: list[ScaleAnchor] = []
    for rate, color, label in points:
        bounded_rate = min(max(rate, 0.0), maximum_rate_uSv_h)
        fraction = regulatory_scale_fraction(
            bounded_rate,
            reference_rate_uSv_h=reference_rate_uSv_h,
            maximum_rate_uSv_h=maximum_rate_uSv_h,
        )
        anchor = ScaleAnchor(bounded_rate, fraction, color, label)
        if anchors and math.isclose(anchors[-1].fraction, fraction, abs_tol=1e-12):
            anchors[-1] = anchor
        else:
            anchors.append(anchor)
    return tuple(anchors)


def public_scale_fraction(
    excess_rate_uSv_h: float,
    *,
    reference_rate_uSv_h: float = PUBLIC_CONTINUOUS_REFERENCE_RATE_USV_H,
    maximum_rate_uSv_h: float = MAX_SIMULATION_SOURCE_STRENGTH_USV_H,
) -> float:
    """Backward-compatible name for :func:`regulatory_scale_fraction`."""

    return regulatory_scale_fraction(
        excess_rate_uSv_h,
        reference_rate_uSv_h=reference_rate_uSv_h,
        maximum_rate_uSv_h=maximum_rate_uSv_h,
    )


def public_scale_anchors(
    *,
    reference_rate_uSv_h: float = PUBLIC_CONTINUOUS_REFERENCE_RATE_USV_H,
    maximum_rate_uSv_h: float = MAX_SIMULATION_SOURCE_STRENGTH_USV_H,
) -> tuple[ScaleAnchor, ...]:
    """Backward-compatible name for :func:`regulatory_scale_anchors`."""

    return regulatory_scale_anchors(
        reference_rate_uSv_h=reference_rate_uSv_h,
        maximum_rate_uSv_h=maximum_rate_uSv_h,
    )
