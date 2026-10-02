"""Fixed-cost regularized particle filter for one static point source."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.special import logsumexp

from ares_mapper.config import (
    AdaptiveGridConfig,
    BoundsConfig,
    DetectorConfig,
    InferenceConfig,
)
from ares_mapper.domain.enums import IdentifiabilityState
from ares_mapper.domain.models import CredibleRegion, ObservationWindow, SourcePosterior
from ares_mapper.inference.identifiability import IdentifiabilityMonitor
from ares_mapper.inference.observation import RadiationObservationModel
from ares_mapper.inference.source_existence import SourceExistenceModel


def normalize_log_weights(log_weights: np.ndarray) -> tuple[np.ndarray, float]:
    evidence = float(logsumexp(log_weights))
    if not math.isfinite(evidence):
        normalized = np.full(len(log_weights), -math.log(len(log_weights)))
        return normalized, -math.inf
    normalized = log_weights - evidence
    return normalized, evidence


def effective_sample_size(log_weights: np.ndarray) -> float:
    weights = np.exp(log_weights)
    return float(1.0 / max(float(np.sum(weights * weights)), 1e-300))


def systematic_resample(weights: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    count = len(weights)
    positions = (float(rng.random()) + np.arange(count)) / count
    cumulative = np.cumsum(weights)
    cumulative[-1] = 1.0
    return np.searchsorted(cumulative, positions, side="right")


def weighted_quantile(
    values: np.ndarray, quantiles: list[float], weights: np.ndarray
) -> np.ndarray:
    order = np.argsort(values)
    sorted_values = values[order]
    sorted_weights = weights[order]
    cumulative = np.cumsum(sorted_weights)
    cumulative /= max(float(cumulative[-1]), 1e-300)
    return np.interp(quantiles, cumulative, sorted_values)


@dataclass(frozen=True, slots=True)
class ParticleUpdate:
    posterior: SourcePosterior
    latency_ms: float
    resampled: bool


class RegularizedParticleFilter:
    """Maintains independent H0 and H1 posteriors with constant memory."""

    def __init__(
        self,
        mission_id: str,
        bounds: BoundsConfig,
        detectors: dict[str, DetectorConfig],
        config: InferenceConfig,
        grid_config: AdaptiveGridConfig,
        *,
        minimum_distance_m: float,
        background_uSv_h: float,
        seed: int,
    ) -> None:
        self.mission_id = mission_id
        self.bounds = bounds
        self.detectors = detectors
        self.config = config
        self.grid_config = grid_config
        self.rng = np.random.Generator(np.random.PCG64(seed + 991))
        self.observation_model = RadiationObservationModel(
            detectors,
            source_z_m=config.source_z_m,
            minimum_distance_m=minimum_distance_m,
        )
        self.existence = SourceExistenceModel(config.source_exists_prior)
        count = config.particles
        background_center = max(
            config.background_min_uSv_h,
            config.background_prior_uSv_h or background_uSv_h,
        )
        background_logs = self.rng.normal(
            math.log(background_center),
            config.background_prior_std_uSv_h / max(background_center, 1e-9),
            count,
        )
        background_logs = np.clip(
            background_logs,
            math.log(config.background_min_uSv_h),
            math.log(config.background_max_uSv_h),
        )
        self.particles = np.column_stack(
            [
                self.rng.uniform(bounds.x_min, bounds.x_max, count),
                self.rng.uniform(bounds.y_min, bounds.y_max, count),
                self.rng.uniform(
                    math.log(config.source_strength_min_uSv_h),
                    math.log(config.source_strength_max_uSv_h),
                    count,
                ),
                background_logs.copy(),
            ]
        )
        self._background_prior_center = background_center
        self.log_weights = np.full(count, -math.log(count), dtype=float)
        self.h0_log_background = background_logs
        self.h0_log_weights = np.full(count, -math.log(count), dtype=float)
        self.update_sequence = 0
        self.last_posterior: SourcePosterior | None = None
        self._prior_refresh_positions: dict[str, np.ndarray] = {}
        self.identifiability = IdentifiabilityMonitor(config, grid_config.observation_cell_m)

    @property
    def weights(self) -> np.ndarray:
        return np.exp(self.log_weights)

    def expected_observation_rate(self, window: ObservationWindow) -> float:
        expected = self.observation_model.expected_rate(self.particles, window)
        return float(np.sum(expected * self.weights))

    def update(self, window: ObservationWindow) -> SourcePosterior:
        refresh_prior = self._spatially_new_window(window)
        prior_weights = self.log_weights.copy()
        prior_h0_weights = self.h0_log_weights.copy()
        log_likelihood_h1 = self.observation_model.log_likelihood_h1(self.particles, window)
        log_likelihood_h0 = self.observation_model.log_likelihood_h0(self.h0_log_background, window)
        self.log_weights, log_evidence_h1 = normalize_log_weights(prior_weights + log_likelihood_h1)
        self.h0_log_weights, log_evidence_h0 = normalize_log_weights(
            prior_h0_weights + log_likelihood_h0
        )
        p_source = self.existence.update(log_evidence_h1, log_evidence_h0)
        ess_before = effective_sample_size(self.log_weights)
        resampled = ess_before < self.config.resample_ess_fraction * len(self.particles)
        if resampled:
            self._resample_h1(refresh_prior=refresh_prior)
        h0_ess = effective_sample_size(self.h0_log_weights)
        if h0_ess < self.config.resample_ess_fraction * len(self.h0_log_background):
            self._resample_h0()

        expected_after = self.expected_observation_rate(window)
        standardized = self.observation_model.standardized_residual(expected_after, window)
        self.identifiability.add(window, standardized)
        self.update_sequence += 1
        posterior = self._summarize(
            window.integration_end_ns,
            p_source,
            ess_before,
            resampled,
            log_evidence_h1,
            log_evidence_h0,
            standardized,
        )
        self.last_posterior = posterior
        return posterior

    def _spatially_new_window(self, window: ObservationWindow) -> bool:
        """Explore new spatial hypotheses when the detector changes position.

        Repeated stationary observations still update every likelihood. Drawing
        fresh prior particles during a dwell would give them no evidence from
        earlier positions and let one near-source point erase that evidence.
        """
        previous = self._prior_refresh_positions.get(window.sensor_id)
        position = np.asarray(window.representative_xyz, dtype=float)
        tolerance = max(1e-6, self.grid_config.observation_cell_m / 4.0)
        moved = previous is None or any(
            np.linalg.norm(np.asarray((point.x_m, point.y_m, point.z_m)) - previous)
            > tolerance
            for point in window.detector_path
        )
        if moved:
            self._prior_refresh_positions[window.sensor_id] = position
        return moved

    def _resample_h1(self, *, refresh_prior: bool = True) -> None:
        indexes = systematic_resample(self.weights, self.rng)
        resampled = self.particles[indexes].copy()
        if self.config.rejuvenation == "liu_west":
            h = self.config.liu_west_h
            a = math.sqrt(max(0.0, 1.0 - h * h))
            mean = np.mean(resampled, axis=0)
            covariance = np.cov(resampled.T) + np.eye(4) * 1e-12
            noise = self.rng.multivariate_normal(np.zeros(4), h * h * covariance, len(resampled))
            resampled = a * resampled + (1.0 - a) * mean + noise
        resampled[:, 0] = np.clip(resampled[:, 0], self.bounds.x_min, self.bounds.x_max)
        resampled[:, 1] = np.clip(resampled[:, 1], self.bounds.y_min, self.bounds.y_max)
        resampled[:, 2] = np.clip(
            resampled[:, 2],
            math.log(self.config.source_strength_min_uSv_h),
            math.log(self.config.source_strength_max_uSv_h),
        )
        resampled[:, 3] = np.clip(
            resampled[:, 3],
            math.log(self.config.background_min_uSv_h),
            math.log(self.config.background_max_uSv_h),
        )
        refresh_count = (
            int(round(len(resampled) * self.config.prior_refresh_fraction))
            if refresh_prior else 0
        )
        if refresh_count:
            refresh_indexes = self.rng.choice(len(resampled), size=refresh_count, replace=False)
            resampled[refresh_indexes] = self._draw_prior(refresh_count)
        self.particles = resampled
        self.log_weights.fill(-math.log(len(self.particles)))

    def _draw_prior(self, count: int) -> np.ndarray:
        """Draw a small exploration component after resampling.

        Liu-West preserves a mode well but cannot recover a spatial hypothesis
        eliminated by an early, weak observation.  A bounded prior component
        keeps that recovery possible without increasing particle count.
        """

        background = self.rng.normal(
            math.log(self._background_prior_center),
            self.config.background_prior_std_uSv_h / max(self._background_prior_center, 1e-9),
            count,
        )
        return np.column_stack(
            [
                self.rng.uniform(self.bounds.x_min, self.bounds.x_max, count),
                self.rng.uniform(self.bounds.y_min, self.bounds.y_max, count),
                self.rng.uniform(
                    math.log(self.config.source_strength_min_uSv_h),
                    math.log(self.config.source_strength_max_uSv_h),
                    count,
                ),
                np.clip(
                    background,
                    math.log(self.config.background_min_uSv_h),
                    math.log(self.config.background_max_uSv_h),
                ),
            ]
        )

    def _resample_h0(self) -> None:
        indexes = systematic_resample(np.exp(self.h0_log_weights), self.rng)
        values = self.h0_log_background[indexes].copy()
        spread = max(float(np.std(values)), 1e-4)
        values += self.rng.normal(0.0, self.config.liu_west_h * spread, len(values))
        self.h0_log_background = np.clip(
            values,
            math.log(self.config.background_min_uSv_h),
            math.log(self.config.background_max_uSv_h),
        )
        self.h0_log_weights.fill(-math.log(len(values)))

    def _summarize(
        self,
        map_time_ns: int,
        p_source: float,
        ess_before: float,
        resampled: bool,
        log_evidence_h1: float,
        log_evidence_h0: float,
        standardized_residual: float,
    ) -> SourcePosterior:
        weights = self.weights
        xy = self.particles[:, :2]
        mean_xy = np.sum(xy * weights[:, None], axis=0)
        histogram, x_edges, y_edges = np.histogram2d(
            xy[:, 0],
            xy[:, 1],
            bins=(
                max(8, int(math.ceil((self.bounds.x_max - self.bounds.x_min) / 0.5))),
                max(8, int(math.ceil((self.bounds.y_max - self.bounds.y_min) / 0.5))),
            ),
            range=(
                (self.bounds.x_min, self.bounds.x_max),
                (self.bounds.y_min, self.bounds.y_max),
            ),
            weights=weights,
        )
        map_index = np.unravel_index(int(np.argmax(histogram)), histogram.shape)
        in_map_cell = (
            (xy[:, 0] >= x_edges[map_index[0]])
            & (xy[:, 0] <= x_edges[map_index[0] + 1])
            & (xy[:, 1] >= y_edges[map_index[1]])
            & (xy[:, 1] <= y_edges[map_index[1] + 1])
        )
        local_weights = weights[in_map_cell]
        if np.any(in_map_cell) and float(np.sum(local_weights)) > 0:
            local_weights = local_weights / float(np.sum(local_weights))
            local_xy = xy[in_map_cell]
            map_xy = (
                float(np.sum(local_xy[:, 0] * local_weights)),
                float(np.sum(local_xy[:, 1] * local_weights)),
            )
        else:
            map_xy = (
                float((x_edges[map_index[0]] + x_edges[map_index[0] + 1]) / 2.0),
                float((y_edges[map_index[1]] + y_edges[map_index[1] + 1]) / 2.0),
            )
        strength = np.exp(self.particles[:, 2])
        background = np.exp(self.particles[:, 3])
        strength_quantiles = weighted_quantile(strength, [0.05, 0.5, 0.95], weights)
        background_quantiles = weighted_quantile(background, [0.05, 0.5, 0.95], weights)
        credible_regions = {
            str(int(probability * 100)): self._credible_region(
                probability, mean_xy, histogram, x_edges, y_edges
            )
            for probability in (0.50, 0.90, 0.95)
        }
        radius_95 = credible_regions["95"].conservative_radius_m
        identifiability, diagnostics = self.identifiability.evaluate(
            xy,
            weights,
            (float(mean_xy[0]), float(mean_xy[1])),
            radius_95,
            p_source,
        )
        detected = (
            p_source >= self.config.source_exists_threshold
            and strength_quantiles[0] > self.config.source_detection_floor_uSv_h
            and identifiability
            not in {
                IdentifiabilityState.INSUFFICIENT,
                IdentifiabilityState.MULTIMODAL,
                IdentifiabilityState.MODEL_MISMATCH,
            }
        )
        entropy = self.identifiability.position_entropy(xy, weights)
        model_diagnostics: dict[str, float | int | str | bool | None] = {**diagnostics}
        model_diagnostics.update(
            {
                "log_evidence_h1": log_evidence_h1,
                "log_evidence_h0": log_evidence_h0,
                "log_bayes_factor": self.existence.log_bayes_factor,
                "resampled": resampled,
                "standardized_residual": standardized_residual,
            }
        )
        snapshot_count = min(64, len(self.particles))
        snapshot_indexes = np.linspace(
            0,
            len(self.particles) - 1,
            snapshot_count,
            dtype=int,
        )
        snapshot_weights = weights[snapshot_indexes]
        snapshot_weights /= max(float(np.sum(snapshot_weights)), 1e-300)
        particle_snapshot = [
            (
                float(self.particles[index, 0]),
                float(self.particles[index, 1]),
                float(self.particles[index, 2]),
                float(self.particles[index, 3]),
            )
            for index in snapshot_indexes
        ]
        log_weight_snapshot = [float(math.log(max(value, 1e-300))) for value in snapshot_weights]
        model_diagnostics["particle_snapshot_count"] = snapshot_count
        model_diagnostics["particle_snapshot_is_subsample"] = snapshot_count < len(self.particles)
        return SourcePosterior(
            mission_id=self.mission_id,
            update_sequence=self.update_sequence,
            map_time_ns=map_time_ns,
            particle_count=len(self.particles),
            particles=particle_snapshot,
            log_weights=log_weight_snapshot,
            p_source_exists=p_source,
            posterior_mean_x_y=(float(mean_xy[0]), float(mean_xy[1])),
            posterior_map_x_y=map_xy,
            posterior_median_strength_at_1m=float(strength_quantiles[1]),
            posterior_strength_interval_90=(
                float(strength_quantiles[0]),
                float(strength_quantiles[2]),
            ),
            posterior_background=float(background_quantiles[1]),
            posterior_background_interval_90=(
                float(background_quantiles[0]),
                float(background_quantiles[2]),
            ),
            credible_regions=credible_regions,
            entropy=entropy,
            effective_sample_size=ess_before,
            identifiability_state=identifiability,
            detected=detected,
            model_diagnostics=model_diagnostics,
        )

    def _credible_region(
        self,
        probability: float,
        center: np.ndarray,
        histogram: np.ndarray,
        x_edges: np.ndarray,
        y_edges: np.ndarray,
    ) -> CredibleRegion:
        flattened = histogram.ravel()
        order = np.argsort(flattened)[::-1]
        cumulative = np.cumsum(flattened[order])
        count = int(np.searchsorted(cumulative, probability, side="left") + 1)
        selected = order[:count]
        cells: list[tuple[float, float, float, float]] = []
        for flat_index in selected[:512]:
            x_index, y_index = np.unravel_index(int(flat_index), histogram.shape)
            cells.append(
                (
                    float(x_edges[x_index]),
                    float(x_edges[x_index + 1]),
                    float(y_edges[y_index]),
                    float(y_edges[y_index + 1]),
                )
            )
        distances = np.linalg.norm(self.particles[:, :2] - center[None, :], axis=1)
        radius = weighted_quantile(distances, [probability], self.weights)[0]
        cell_area = float((x_edges[1] - x_edges[0]) * (y_edges[1] - y_edges[0]))
        return CredibleRegion(
            probability=probability,
            center_x_m=float(center[0]),
            center_y_m=float(center[1]),
            conservative_radius_m=float(radius),
            area_m2=count * cell_area,
            cells=cells,
        )

    def render_samples(self, count: int, *, seed: int) -> tuple[np.ndarray, np.ndarray]:
        """Draw deterministic posterior field parameters and H1-existence flags."""

        rng = np.random.Generator(np.random.PCG64(seed))
        count = min(max(1, count), len(self.particles))
        indexes = rng.choice(len(self.particles), size=count, replace=True, p=self.weights)
        samples = self.particles[indexes].copy()
        exists = rng.random(count) < self.existence.probability
        if np.any(~exists):
            h0_indexes = rng.choice(
                len(self.h0_log_background),
                size=int(np.count_nonzero(~exists)),
                replace=True,
                p=np.exp(self.h0_log_weights),
            )
            samples[~exists, 3] = self.h0_log_background[h0_indexes]
        return samples, exists

    def source_probability(
        self, points_xy: np.ndarray, *, bandwidth_m: float, cell_area_m2: float
    ) -> np.ndarray:
        weights = self.weights
        dx = points_xy[:, 0, None] - self.particles[None, :, 0]
        dy = points_xy[:, 1, None] - self.particles[None, :, 1]
        bandwidth_sq = max(bandwidth_m, 1e-6) ** 2
        density = np.sum(
            np.exp(-0.5 * (dx * dx + dy * dy) / bandwidth_sq) * weights[None, :],
            axis=1,
        ) / (2.0 * math.pi * bandwidth_sq)
        return np.clip(
            density * cell_area_m2 * self.existence.probability,
            0.0,
            1.0,
        )
