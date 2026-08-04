"""Incremental single-source fit and physically informed residual fusion."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from scipy.optimize import least_squares

from ares_mapper.config import BoundsConfig
from ares_mapper.domain.enums import MappingQuality
from ares_mapper.domain.models import MappedSample


@dataclass(frozen=True, slots=True)
class SourceEstimate:
    x_m: float
    y_m: float
    strength_at_1m_uSv_h: float
    background_uSv_h: float
    rmse_uSv_h: float
    confidence_radius_m: float | None
    sample_count: int
    unique_position_count: int
    quality: str
    method: str = "weighted_robust_inverse_square"

    def as_dict(self) -> dict[str, float | int | str | None]:
        return asdict(self)


def observation_weights(
    samples: list[MappedSample],
) -> tuple[np.ndarray, dict[str, float | None]]:
    """Build bounded weights from counting, timing, pose and dose-integral evidence."""
    if not samples:
        return np.asarray([], dtype=float), {"cumulative_closure_error_uSv": None}
    weights = np.ones(len(samples), dtype=float)
    for index, sample in enumerate(samples):
        integration_s = max(0.1, float(sample.integration_time_s or 1.0))
        weights[index] *= min(2.0, max(0.5, integration_s**0.5))
        if sample.position_std_m is not None:
            weights[index] *= 1.0 / (1.0 + (max(0.0, sample.position_std_m) / 0.05) ** 2)
        weights[index] *= 1.0 / (1.0 + (max(0.0, sample.path_length_m) / 0.75) ** 2)
        if sample.cpm is not None:
            count_factor = (max(sample.cpm, 0) + 4.0) ** 0.25 / 2.0
            weights[index] *= min(1.8, max(0.55, count_factor))
        if sample.mapping_quality == MappingQuality.DEGRADED:
            weights[index] *= 0.45
        weights[index] *= 1.0 / (1.0 + (max(0.0, sample.sync_error_estimate_ms) / 250.0) ** 2)

    ordered = sorted(
        enumerate(samples),
        key=lambda pair: pair[1].effective_measurement_time_ns,
    )
    predicted_total = 0.0
    observed_total = 0.0
    for (previous_index, previous), (current_index, current) in zip(
        ordered[:-1],
        ordered[1:],
        strict=True,
    ):
        delta_s = (
            current.effective_measurement_time_ns - previous.effective_measurement_time_ns
        ) / 1_000_000_000
        observed_delta = current.cumulative_dose_uSv - previous.cumulative_dose_uSv
        if delta_s <= 0 or observed_delta < 0:
            continue
        expected_delta = (
            0.5
            * (previous.dose_rate_uSv_h_filtered + current.dose_rate_uSv_h_filtered)
            * delta_s
            / 3600.0
        )
        predicted_total += expected_delta
        observed_total += observed_delta
        tolerance = max(0.01, 4.0 * expected_delta)
        if abs(observed_delta - expected_delta) > tolerance:
            weights[previous_index] *= 0.7
            weights[current_index] *= 0.7

    weights /= max(float(np.mean(weights)), 1e-12)
    closure = (
        observed_total - predicted_total if predicted_total > 0.0 or observed_total > 0.0 else None
    )
    return weights, {"cumulative_closure_error_uSv": closure}


def fit_single_point_source(
    samples: list[MappedSample],
    bounds: BoundsConfig,
    *,
    minimum_samples: int = 6,
    reference_distance_m: float = 1.0,
    minimum_distance_m: float = 0.25,
) -> tuple[SourceEstimate | None, dict[str, float | None]]:
    valid = [
        sample
        for sample in samples
        if sample.mapping_quality != MappingQuality.REJECTED
        and np.isfinite(sample.dose_rate_uSv_h_filtered)
    ]
    weights, diagnostics = observation_weights(valid)
    if len(valid) < minimum_samples:
        return None, diagnostics
    points = np.asarray([(sample.sensor_x_m, sample.sensor_y_m) for sample in valid])
    values = np.asarray(
        [sample.dose_rate_uSv_h_filtered for sample in valid],
        dtype=float,
    )
    unique_count = len(np.unique(np.round(points, decimals=2), axis=0))
    spatial_span = float(np.linalg.norm(np.ptp(points, axis=0)))
    if unique_count < minimum_samples or spatial_span < 0.5:
        return None, diagnostics

    diagonal = float(np.hypot(bounds.x_max - bounds.x_min, bounds.y_max - bounds.y_min))
    maximum_value = max(float(np.max(values)), 0.01)
    background_guess = max(0.0, float(np.percentile(values, 15)))
    strength_upper = max(10.0, maximum_value * max(diagonal, 1.0) ** 2 * 4.0)
    background_upper = max(2.0, maximum_value * 2.0)
    lower = np.asarray([bounds.x_min, bounds.y_min, 0.0, 0.0])
    upper = np.asarray([bounds.x_max, bounds.y_max, strength_upper, background_upper])
    hottest = points[np.argsort(values)[-min(4, len(values)) :]]
    center = np.asarray([(bounds.x_min + bounds.x_max) / 2.0, (bounds.y_min + bounds.y_max) / 2.0])
    seeds = [center, *hottest]

    def model(parameters: np.ndarray, locations: np.ndarray) -> np.ndarray:
        source_xy = parameters[:2]
        strength = parameters[2]
        background = parameters[3]
        distance = np.linalg.norm(locations - source_xy, axis=1)
        effective = np.maximum(distance, minimum_distance_m)
        return background + strength * (reference_distance_m / effective) ** 2

    sqrt_weights = np.sqrt(np.maximum(weights, 1e-6))

    def residual(parameters: np.ndarray) -> np.ndarray:
        return sqrt_weights * (model(parameters, points) - values)

    best = None
    best_cost = float("inf")
    value_range = max(float(np.ptp(values)), 0.02)
    for seed in seeds:
        seed_distance = np.linalg.norm(points - seed, axis=1)
        strength_guess = max(
            0.01,
            value_range * max(float(np.percentile(seed_distance, 60)), minimum_distance_m) ** 2,
        )
        initial = np.asarray(
            [seed[0], seed[1], min(strength_guess, strength_upper), background_guess]
        )
        result = least_squares(
            residual,
            initial,
            bounds=(lower, upper),
            loss="soft_l1",
            f_scale=max(0.03, float(np.median(np.abs(values - np.median(values))))),
            max_nfev=500,
        )
        score = float(np.mean(residual(result.x) ** 2))
        if result.success and score < best_cost:
            best = result
            best_cost = score
    if best is None:
        return None, diagnostics

    predicted = model(best.x, points)
    rmse = float(np.sqrt(np.average((predicted - values) ** 2, weights=weights)))
    confidence_radius: float | None = None
    if best.jac.shape[0] > best.jac.shape[1]:
        degrees = max(1, best.jac.shape[0] - best.jac.shape[1])
        residual_variance = float(np.sum(best.fun**2) / degrees)
        covariance = np.linalg.pinv(best.jac.T @ best.jac) * residual_variance
        eigenvalues = np.linalg.eigvalsh(covariance[:2, :2])
        radius = 2.447 * float(np.sqrt(max(float(np.max(eigenvalues)), 0.0)))
        if np.isfinite(radius):
            confidence_radius = min(radius, diagonal * 2.0)

    quality = "provisional"
    if confidence_radius is not None and confidence_radius <= 1.0 and len(valid) >= 10:
        quality = "converging"
    if confidence_radius is not None and confidence_radius <= 0.45 and len(valid) >= 20:
        quality = "stable"
    estimate = SourceEstimate(
        x_m=float(best.x[0]),
        y_m=float(best.x[1]),
        strength_at_1m_uSv_h=float(best.x[2]),
        background_uSv_h=float(best.x[3]),
        rmse_uSv_h=rmse,
        confidence_radius_m=confidence_radius,
        sample_count=len(valid),
        unique_position_count=unique_count,
        quality=quality,
    )
    return estimate, diagnostics


def inverse_square_field(
    points: np.ndarray,
    estimate: SourceEstimate,
    *,
    reference_distance_m: float = 1.0,
    minimum_distance_m: float = 0.25,
) -> np.ndarray:
    source = np.asarray([estimate.x_m, estimate.y_m])
    distance = np.linalg.norm(points - source, axis=1)
    effective = np.maximum(distance, minimum_distance_m)
    return (
        estimate.background_uSv_h
        + estimate.strength_at_1m_uSv_h * (reference_distance_m / effective) ** 2
    )
