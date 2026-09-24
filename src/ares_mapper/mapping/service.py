"""Stateful V0.3 probabilistic map engine for live missions and replay."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree
from scipy.special import ndtr

from ares_mapper.config import (
    AdaptiveGridConfig,
    DetectorConfig,
    InferenceConfig,
    MappingConfig,
    ResidualConfig,
    WorldConfig,
)
from ares_mapper.domain.enums import (
    EvidenceKind,
    IdentifiabilityState,
    ObservationMode,
    Quality,
)
from ares_mapper.domain.models import (
    DetectorPathPoint,
    ExposureSummary,
    MappedSample,
    MapPrediction,
    ObservationWindow,
    RadiationSample,
    SourcePosterior,
)
from ares_mapper.inference.particle_filter import RegularizedParticleFilter
from ares_mapper.mapping.exposure import DoseAudit, MissionExposureTracker
from ares_mapper.mapping.filters import SampleFilter
from ares_mapper.mapping.grid import GridSpec
from ares_mapper.mapping.metrics import map_metrics
from ares_mapper.mapping.observation_grid import ObservationGrid
from ares_mapper.mapping.reconstruction import AdaptiveFieldReconstructor
from ares_mapper.simulation.radiation_field import RadiationField


@dataclass(frozen=True, slots=True)
class ObservationUpdate:
    mapped_sample: MappedSample
    posterior: SourcePosterior
    dose_audit: DoseAudit
    latency_ms: float


class MapService:
    """Sequential posterior updates plus independently scheduled map rendering."""

    def __init__(
        self,
        mission_id: str,
        world: WorldConfig,
        config: MappingConfig,
        field: RadiationField | None = None,
        *,
        inference: InferenceConfig | None = None,
        grid_config: AdaptiveGridConfig | None = None,
        residual_config: ResidualConfig | None = None,
        detectors: list[DetectorConfig] | None = None,
        seed: int = 42,
    ) -> None:
        self.mission_id = mission_id
        self.world = world
        self.config = config
        self.field = field
        self.inference_config = inference or InferenceConfig()
        self.grid_config = grid_config or AdaptiveGridConfig()
        self.residual_config = residual_config or ResidualConfig()
        detector_list = detectors or [DetectorConfig(sensor_id="detector")]
        self.detectors = {detector.sensor_id: detector for detector in detector_list}
        raster_resolution = max(config.grid_resolution_m, self.grid_config.minimum_cell_m)
        self.grid = GridSpec.from_bounds(world.bounds_m, raster_resolution)
        self.samples: list[MappedSample] = []
        self.observations: list[ObservationWindow] = []
        self.raw_sample_count = 0
        self.raw_observation_count = 0
        self.sample_history_limit = 5000
        self.filter = SampleFilter(config.filter)
        self.latest: MapPrediction | None = None
        self.latest_posterior: SourcePosterior | None = None
        self.observation_grid = ObservationGrid(world.bounds_m, self.grid_config.observation_cell_m)
        self.particle_filter = RegularizedParticleFilter(
            mission_id,
            world.bounds_m,
            self.detectors,
            self.inference_config,
            self.grid_config,
            minimum_distance_m=config.source_minimum_distance_m,
            background_uSv_h=world.background.dose_rate_uSv_h,
            seed=seed,
        )
        self.reconstructor = AdaptiveFieldReconstructor(
            world,
            self.inference_config,
            self.grid_config,
            self.residual_config,
            self.detectors,
            self.particle_filter,
            self.observation_grid,
            minimum_distance_m=config.source_minimum_distance_m,
            display_smoothing_alpha=config.global_model_smoothing_alpha,
        )
        self.exposure_trackers = {
            detector.sensor_id: MissionExposureTracker(
                detector.cumulative_quantization_uSv,
                self.grid_config.probability_threshold_uSv_h,
            )
            for detector in detector_list
        }
        self.posterior_latencies_ms: list[float] = []
        self.render_latencies_ms: list[float] = []
        self._stable_posterior_updates = 0
        self._unstable_posterior_updates = 0
        self._global_model_ready = False
        self._global_model_blend = 0.0
        self._lock = threading.RLock()

    def add_sample(self, sample: MappedSample) -> MappedSample:
        """Compatibility entry point for old tests and V0.2 mission databases."""

        window = self._window_from_mapped(sample)
        return self.add_observation(window, sample).mapped_sample

    def add_observation(self, window: ObservationWindow, mapped: MappedSample) -> ObservationUpdate:
        """Update the posterior in O(P·L·D), independent of mission history."""

        with self._lock:
            started = time.perf_counter_ns()
            detector = self._ensure_detector(window.sensor_id)
            if (
                window.evidence_kind == EvidenceKind.INSTANTANEOUS
                and window.observation_mode.value != detector.observation_mode
            ):
                window = window.model_copy(
                    update={"observation_mode": ObservationMode(detector.observation_mode)}
                )
            filtered = self.filter.apply(mapped)
            posterior = self.particle_filter.update(window)
            observed_rate = self.particle_filter.observation_model.observed_rate(window)
            expected_after = self.particle_filter.expected_observation_rate(window)
            measurement_std = self._measurement_std_uSv_h(
                detector,
                observed_rate,
                window,
            )
            stable = (
                posterior.detected
                and posterior.identifiability_state == IdentifiabilityState.STABLE
            )
            was_global_model_ready = self._global_model_ready
            transition_step = 1.0 / self.config.global_model_transition_updates
            if stable:
                self._stable_posterior_updates += 1
                self._unstable_posterior_updates = 0
                if not self._global_model_ready:
                    self._global_model_ready = (
                        self._stable_posterior_updates >= self.config.global_model_stable_updates
                    )
                if self._global_model_ready:
                    self._global_model_blend = min(
                        1.0,
                        self._global_model_blend + transition_step,
                    )
            else:
                self._stable_posterior_updates = 0
                self._unstable_posterior_updates += 1
                if (
                    self._global_model_ready
                    and self._unstable_posterior_updates
                    > self.config.global_model_unstable_grace_updates
                ):
                    self._global_model_blend = max(
                        0.0,
                        self._global_model_blend - transition_step,
                    )
                    if self._global_model_blend <= 0:
                        self._global_model_ready = False
            if not self._global_model_ready:
                self._global_model_blend = 0.0
                if was_global_model_ready:
                    self.reconstructor.reset_display_state()
            physical_for_residual = expected_after if self._global_model_ready else observed_rate
            self.observation_grid.add(
                window,
                observed_rate,
                physical_for_residual,
                measurement_std,
            )
            tracker = self.exposure_trackers.setdefault(
                window.sensor_id,
                MissionExposureTracker(detector.cumulative_quantization_uSv),
            )
            dose_audit = (
                tracker.update(window)
                if window.evidence_kind == EvidenceKind.INSTANTANEOUS
                else DoseAudit(
                    "GAP_EVIDENCE_FUSED",
                    path_integral_uSv=(
                        window.radiation_sample.dose_rate_uSv_h * window.integration_time_s / 3600.0
                    ),
                    recovered_rate_uSv_h=(window.radiation_sample.dose_rate_uSv_h),
                    recovered_start_ns=window.integration_start_ns,
                    recovered_end_ns=window.integration_end_ns,
                )
            )
            self._append_bounded(self.samples, filtered)
            self._append_bounded(self.observations, window)
            self.raw_sample_count += 1
            self.raw_observation_count += 1
            self.latest_posterior = posterior
            latency_ms = (time.perf_counter_ns() - started) / 1_000_000.0
            self._append_latency(self.posterior_latencies_ms, latency_ms)
            return ObservationUpdate(filtered, posterior, dose_audit, latency_ms)

    def predict(
        self,
        at_time_ns: int,
        *,
        temporal_mode: str | None = None,
        time_slice: tuple[int, int] | None = None,
        include_truth: bool = True,
    ) -> MapPrediction:
        del time_slice
        with self._lock:
            started = time.perf_counter_ns()
            mode = temporal_mode or self.config.temporal_mode
            if self.latest_posterior is None:
                prediction = self._empty_prediction(at_time_ns, mode)
                self.latest = prediction
                return prediction
            detector_height = self._detector_height()
            if self._global_model_ready:
                local_arrays = self._measured_gradient_arrays(self._blank_map_arrays())
                reconstruction = self.reconstructor.reconstruct(
                    at_time_ns,
                    self.grid,
                    self.latest_posterior,
                    detector_height_m=detector_height,
                    update_display_state=(
                        self.latest_posterior.detected
                        and self.latest_posterior.identifiability_state
                        == IdentifiabilityState.STABLE
                    ),
                )
                if self._global_model_blend < 1.0:
                    arrays = self._blend_map_arrays(
                        local_arrays,
                        reconstruction.arrays,
                        self._global_model_blend,
                    )
                    reconstruction_mode = "physical_transition"
                else:
                    arrays = reconstruction.arrays
                    reconstruction_mode = "physical_global"
                active_leaf_count = reconstruction.leaf_count
                physical_minimum_cell_m = reconstruction.physical_minimum_cell_m
                adaptive_cells = reconstruction.cells
            else:
                # Before identifiability, only the bounded measurement layer is
                # visible.  Building a hidden global quadtree here wasted most
                # of the render budget and also refined around irrelevant
                # exploratory particles.
                arrays = self._measured_gradient_arrays(self._blank_map_arrays())
                reconstruction_mode = "measured_local"
                active_leaf_count = 0
                physical_minimum_cell_m = self.grid_config.minimum_cell_m
                adaptive_cells = []
            truth_2d: np.ndarray | None = None
            metrics: dict[str, float | int | str | bool | None] = {
                "sample_count": self.raw_sample_count,
                "observation_count": self.raw_observation_count,
                "coverage_percent": float(100.0 * np.mean(arrays["coverage_mask"])),
                "active_quadtree_leaves": active_leaf_count,
                "physical_minimum_cell_m": physical_minimum_cell_m,
                "p_source_exists": self.latest_posterior.p_source_exists,
                "effective_sample_size": self.latest_posterior.effective_sample_size,
                "identifiability_state": self.latest_posterior.identifiability_state.value,
                "source_detected": self.latest_posterior.detected,
                "reconstruction_mode": reconstruction_mode,
                "global_model_ready": self._global_model_ready,
                "global_model_blend": self._global_model_blend,
                "stable_posterior_updates": self._stable_posterior_updates,
                "unstable_posterior_updates": self._unstable_posterior_updates,
                "posterior_update_latency_p95_ms": self._percentile(
                    self.posterior_latencies_ms, 95
                ),
                "no_radiation_sample_dropped_by_processing": True,
            }
            exposure = self._combined_exposure()
            metrics.update(
                {
                    "cumulative_closure_error_uSv": exposure.cumulative_closure_error_uSv,
                    "recovered_gap_count": exposure.recovered_gap_count,
                    "dose_reset_count": exposure.reset_count,
                }
            )
            if self.field is not None and include_truth:
                truth_2d = self.field.grid(
                    self.grid.x_coordinates_m,
                    self.grid.y_coordinates_m,
                    detector_height,
                    at_time_ns / 1_000_000_000,
                )
                full_mask = np.isfinite(arrays["mean"])
                truth_metrics = map_metrics(
                    arrays["mean"],
                    truth_2d,
                    full_mask,
                    self.grid.x_coordinates_m,
                    self.grid.y_coordinates_m,
                )
                metrics.update(
                    {
                        "field_MAE": truth_metrics["mae_uSv_h"],
                        "field_RMSE": truth_metrics["rmse_uSv_h"],
                        "field_hotspot_error_m": truth_metrics["hotspot_error_m"],
                    }
                )
                source_error = self._source_position_error() if self._global_model_ready else None
                if source_error is not None:
                    metrics["source_position_error_m"] = source_error
            source_estimate = self._source_estimate() if self._global_model_ready else None
            hotspot = self._hotspot(arrays["mean"])
            render_ms = (time.perf_counter_ns() - started) / 1_000_000.0
            self._append_latency(self.render_latencies_ms, render_ms)
            metrics["render_latency_ms"] = render_ms
            metrics["render_latency_p95_ms"] = self._percentile(self.render_latencies_ms, 95)
            metrics["posterior_complexity_evaluations"] = (
                self.inference_config.particles
                * max(
                    1,
                    int(
                        np.mean(
                            [len(item.detector_path) for item in self.observations[-20:]] or [1]
                        )
                    ),
                )
                * max(1, len(self.detectors))
            )
            prediction = MapPrediction(
                mission_id=self.mission_id,
                frame_id=self.world.frame_id,
                map_time_ns=at_time_ns,
                temporal_mode=mode,
                time_window_start_ns=0 if self.raw_observation_count else None,
                time_window_end_ns=at_time_ns,
                x_coordinates_m=self.grid.x_coordinates_m.tolist(),
                y_coordinates_m=self.grid.y_coordinates_m.tolist(),
                values_row_major=_optional_float_list(arrays["mean"]),
                coverage_mask_row_major=arrays["coverage_mask"].ravel().tolist(),
                p05_values_row_major=_optional_float_list(arrays["p05"]),
                p50_values_row_major=_optional_float_list(arrays["p50"]),
                p95_values_row_major=_optional_float_list(arrays["p95"]),
                uncertainty_values_row_major=_optional_float_list(arrays["uncertainty"]),
                relative_uncertainty_row_major=_optional_float_list(arrays["relative_uncertainty"]),
                coverage_time_row_major=_optional_float_list(arrays["coverage_time"]),
                exposure_values_row_major=_optional_float_list(arrays["exposure"]),
                source_probability_row_major=_optional_float_list(arrays["source_probability"]),
                probability_above_threshold_row_major=_optional_float_list(
                    arrays["probability_above"]
                ),
                distance_to_support_row_major=_optional_float_list(arrays["distance_to_support"]),
                model_fraction_row_major=_optional_float_list(arrays["model_fraction"]),
                residual_fraction_row_major=_optional_float_list(arrays["residual_fraction"]),
                truth_values_row_major=(
                    _optional_float_list(truth_2d) if truth_2d is not None else None
                ),
                grid_shape=self.grid.shape,
                sample_count=self.raw_sample_count,
                interpolator=(
                    "posterior_inverse_square_plus_local_residual"
                    if self._global_model_ready
                    else "bounded_local_measurement_gradient"
                ),
                parameters={
                    "particles": self.inference_config.particles,
                    "render_particles": self.inference_config.render_particles,
                    "observation_model": "per_detector",
                    "adaptive_grid": "quadtree",
                    "residual": "local_idw",
                    "residual_neighbors": self.residual_config.neighbors,
                    "local_support_radius_m": self.config.influence_radius_m,
                    "residual_support_radius_m": (
                        self.residual_config.maximum_support_cells
                        * self.grid_config.observation_cell_m
                    ),
                    "maximum_active_leaves": self.grid_config.maximum_leaves,
                    "global_model_requires_stable_updates": (
                        self.config.global_model_stable_updates
                    ),
                    "global_model_transition_updates": (
                        self.config.global_model_transition_updates
                    ),
                    "global_model_unstable_grace_updates": (
                        self.config.global_model_unstable_grace_updates
                    ),
                    "global_model_smoothing_alpha": (self.config.global_model_smoothing_alpha),
                    "maximum_relative_residual_correction": (
                        self.residual_config.maximum_relative_correction
                    ),
                    "response_compensation": any(
                        detector.response_compensation_enabled
                        and detector.response_time_constant_s > 0
                        for detector in self.detectors.values()
                    ),
                },
                hotspot=hotspot,
                source_estimate=source_estimate,
                source_posterior=self.latest_posterior,
                adaptive_cells=adaptive_cells,
                exposure=exposure,
                layers=[
                    "dose_rate",
                    "uncertainty",
                    "coverage",
                    "exposure",
                    "source_probability",
                    "probability_above_threshold",
                    "measurements",
                    "trajectory",
                    "simulation_truth",
                ],
                metrics=metrics,
            )
            self.latest = prediction
            return prediction

    def _measured_gradient_arrays(
        self,
        arrays: dict[str, np.ndarray],
    ) -> dict[str, np.ndarray]:
        """Render only the region supported by measurements.

        Before the source model is identifiable, a global inverse-square field
        can have several equally plausible maxima on opposite sides of a nearly
        linear trajectory.  This bounded interpolation cannot create values
        hotter than its measured support and leaves unsupported areas unknown.
        """

        support_points, support_rates, support_variances, support_times = (
            self.observation_grid.support_arrays()
        )
        xx, yy = np.meshgrid(
            self.grid.x_coordinates_m,
            self.grid.y_coordinates_m,
        )
        queries = np.column_stack((xx.ravel(), yy.ravel()))
        shape = self.grid.shape
        count = len(queries)
        local_mean = np.full(count, np.nan, dtype=float)
        local_std = np.full(count, np.nan, dtype=float)
        nearest = np.full(count, np.nan, dtype=float)
        if len(support_points):
            neighbors = min(self.residual_config.neighbors, len(support_points))
            support_radius_m = max(self.config.influence_radius_m, 1e-6)
            distances, indexes = cKDTree(support_points).query(
                queries,
                k=neighbors,
                distance_upper_bound=support_radius_m,
            )
            if neighbors == 1:
                distances = distances[:, None]
                indexes = indexes[:, None]
            valid = (
                np.isfinite(distances)
                & (distances < support_radius_m)
                & (indexes < len(support_rates))
            )
            safe_indexes = np.where(valid, indexes, 0)
            noise_floor = max(
                (detector.robust_base_std_uSv_h for detector in self.detectors.values()),
                default=0.03,
            )
            inverse_variance = 1.0 / (support_variances[safe_indexes] + noise_floor**2)
            distance_weight = (
                1.0
                / np.maximum(
                    distances + self.config.epsilon_m,
                    1e-6,
                )
                ** self.config.idw_power
            )
            normalized_distance = np.clip(
                distances / support_radius_m,
                0.0,
                1.0,
            )
            compact_taper = (1.0 - normalized_distance**2) ** 2
            time_weight = np.sqrt(np.maximum(support_times[safe_indexes], 1e-3))
            weights = np.where(
                valid,
                compact_taper * distance_weight * inverse_variance * time_weight,
                0.0,
            )
            denominator = np.sum(weights, axis=1)
            supported = denominator > 0
            normalized = np.divide(
                weights,
                denominator[:, None],
                out=np.zeros_like(weights),
                where=denominator[:, None] > 0,
            )
            local_values = support_rates[safe_indexes]
            local_mean[supported] = np.sum(
                normalized * local_values,
                axis=1,
            )[supported]
            spatial_variance = np.sum(
                normalized * (local_values - np.nan_to_num(local_mean)[:, None]) ** 2,
                axis=1,
            )
            measurement_variance = np.sum(
                normalized**2 * (support_variances[safe_indexes] + noise_floor**2),
                axis=1,
            )
            nearest_values = distances[:, 0]
            finite_nearest = np.isfinite(nearest_values)
            nearest[finite_nearest] = nearest_values[finite_nearest]
            distance_penalty = (
                np.nan_to_num(nearest, nan=support_radius_m) / support_radius_m
            ) ** 2 * (noise_floor + 0.08 * np.nan_to_num(local_mean, nan=0.0)) ** 2
            variance = np.maximum(
                measurement_variance + spatial_variance + distance_penalty,
                noise_floor**2 / max(1, neighbors),
            )
            local_std[supported] = np.sqrt(variance[supported])

        p05 = np.maximum(0.0, local_mean - 1.645 * local_std)
        p95 = local_mean + 1.645 * local_std
        relative = np.divide(
            local_std,
            np.maximum(local_mean, 1e-6),
            out=np.full(count, np.nan, dtype=float),
            where=np.isfinite(local_mean),
        )
        probability_above = ndtr(
            np.divide(
                local_mean - self.grid_config.probability_threshold_uSv_h,
                local_std,
                out=np.full(count, np.nan, dtype=float),
                where=np.isfinite(local_std) & (local_std > 0),
            )
        )
        finite = np.isfinite(local_mean)
        coverage, _, exposure, _ = self.observation_grid.query_stats(queries)
        arrays["mean"] = local_mean.reshape(shape)
        arrays["p05"] = p05.reshape(shape)
        arrays["p50"] = local_mean.reshape(shape)
        arrays["p95"] = p95.reshape(shape)
        arrays["uncertainty"] = local_std.reshape(shape)
        arrays["relative_uncertainty"] = relative.reshape(shape)
        arrays["source_probability"] = np.zeros(shape, dtype=float)
        arrays["probability_above"] = probability_above.reshape(shape)
        arrays["distance_to_support"] = nearest.reshape(shape)
        arrays["model_fraction"] = np.where(finite, 0.0, np.nan).reshape(shape)
        arrays["residual_fraction"] = np.where(finite, 1.0, np.nan).reshape(shape)
        arrays["coverage_time"] = coverage.reshape(shape)
        arrays["exposure"] = exposure.reshape(shape)
        arrays["coverage_mask"] = finite.reshape(shape)
        return arrays

    def _blend_map_arrays(
        self,
        local: dict[str, np.ndarray],
        physical: dict[str, np.ndarray],
        fraction: float,
    ) -> dict[str, np.ndarray]:
        """Fade from measured support to the stable physical field."""

        alpha = min(1.0, max(0.0, fraction))
        result = {key: value.copy() for key, value in physical.items()}
        local_support = np.isfinite(local["mean"])
        background = (
            self.latest_posterior.posterior_background
            if self.latest_posterior is not None
            else self.world.background.dose_rate_uSv_h
        )
        for key in ("mean", "p05", "p50", "p95"):
            baseline = np.where(local_support, local[key], background)
            result[key] = baseline + alpha * (physical[key] - baseline)

        local_uncertainty = np.where(
            local_support,
            local["uncertainty"],
            0.0,
        )
        result["uncertainty"] = (1.0 - alpha) * local_uncertainty + alpha * np.nan_to_num(
            physical["uncertainty"], nan=0.0
        )
        result["relative_uncertainty"] = np.divide(
            result["uncertainty"],
            np.maximum(result["mean"], 1e-9),
            out=np.zeros_like(result["mean"]),
            where=np.isfinite(result["mean"]),
        )
        result["source_probability"] = alpha * physical["source_probability"]
        result["probability_above"] = np.where(
            local_support,
            (1.0 - alpha) * np.nan_to_num(local["probability_above"], nan=0.0)
            + alpha * np.nan_to_num(physical["probability_above"], nan=0.0),
            alpha * np.nan_to_num(physical["probability_above"], nan=0.0),
        )
        result["model_fraction"] = np.where(
            local_support,
            alpha * np.nan_to_num(physical["model_fraction"], nan=1.0),
            1.0,
        )
        result["residual_fraction"] = 1.0 - result["model_fraction"]
        return result

    def _blank_map_arrays(self) -> dict[str, np.ndarray]:
        shape = self.grid.shape
        return {
            "mean": np.full(shape, np.nan),
            "p05": np.full(shape, np.nan),
            "p50": np.full(shape, np.nan),
            "p95": np.full(shape, np.nan),
            "uncertainty": np.full(shape, np.nan),
            "relative_uncertainty": np.full(shape, np.nan),
            "coverage_time": np.zeros(shape),
            "exposure": np.zeros(shape),
            "source_probability": np.zeros(shape),
            "probability_above": np.full(shape, np.nan),
            "distance_to_support": np.full(shape, np.nan),
            "model_fraction": np.full(shape, np.nan),
            "residual_fraction": np.full(shape, np.nan),
            "coverage_mask": np.zeros(shape, dtype=bool),
        }

    def _window_from_mapped(self, sample: MappedSample) -> ObservationWindow:
        detector = self._ensure_detector(sample.sensor_id)
        duration = max(1e-6, float(sample.integration_time_s or 1.0))
        start_ns = sample.integration_start_time_ns
        end_ns = sample.integration_end_time_ns
        if start_ns is None or end_ns is None or end_ns <= start_ns:
            start_ns = sample.effective_measurement_time_ns - int(duration * 1e9 / 2)
            end_ns = start_ns + int(duration * 1e9)
        radiation = RadiationSample(
            mission_id=sample.mission_id,
            sensor_id=sample.sensor_id,
            sequence=sample.radiation_sequence,
            time_domain_id=sample.time_domain_id,
            timeline_time_ns=sample.effective_measurement_time_ns,
            received_utc_ns=0,
            received_monotonic_ns=sample.effective_measurement_time_ns,
            effective_measurement_time_ns=sample.effective_measurement_time_ns,
            dose_rate_uSv_h=sample.dose_rate_uSv_h_filtered,
            cumulative_dose_uSv=sample.cumulative_dose_uSv,
            cps=sample.cps,
            cpm=sample.cpm,
            average_dose_rate_uSv_h=sample.average_dose_rate_uSv_h,
            timer_s=sample.timer_s,
            timed_dose_uSv=sample.timed_dose_uSv,
            integration_time_s=duration,
            integration_start_time_ns=start_ns,
            integration_end_time_ns=end_ns,
            quality=sample.radiation_quality,
            alarm=sample.alarm,
            calibration_id=detector.calibration_id,
        )
        return ObservationWindow(
            mission_id=sample.mission_id,
            sensor_id=sample.sensor_id,
            observation_sequence=sample.mapped_sequence,
            radiation_sample=radiation,
            detector_path=[
                DetectorPathPoint(
                    timeline_time_ns=sample.effective_measurement_time_ns,
                    x_m=sample.sensor_x_m,
                    y_m=sample.sensor_y_m,
                    z_m=sample.sensor_z_m,
                    yaw_rad=sample.sensor_yaw_rad,
                    position_std_m=float(sample.position_std_m or 0.0),
                )
            ],
            path_time_weights_s=[duration],
            integration_start_ns=start_ns,
            integration_end_ns=end_ns,
            integration_time_s=duration,
            maximum_pose_gap_ms=sample.max_pose_gap_ms,
            sync_error_ms=sample.sync_error_estimate_ms,
            observation_mode=ObservationMode(detector.observation_mode),
            evidence_kind=EvidenceKind.INSTANTANEOUS,
            quality_flags=list(sample.flags),
            quality=(
                Quality.VALID if sample.mapping_quality.value == "VALID" else Quality.DEGRADED
            ),
        )

    def _ensure_detector(self, sensor_id: str) -> DetectorConfig:
        detector = self.detectors.get(sensor_id)
        if detector is not None:
            return detector
        detector = DetectorConfig(sensor_id=sensor_id)
        self.detectors[sensor_id] = detector
        self.particle_filter.detectors[sensor_id] = detector
        self.particle_filter.observation_model.detectors[sensor_id] = detector
        self.exposure_trackers[sensor_id] = MissionExposureTracker(
            detector.cumulative_quantization_uSv
        )
        return detector

    @staticmethod
    def _measurement_std_uSv_h(
        detector: DetectorConfig,
        observed_rate_uSv_h: float,
        window: ObservationWindow,
    ) -> float:
        """Return the per-reading uncertainty used by the spatial fusion layer."""

        timing_fraction = min(1.0, max(0.0, window.sync_error_ms) / 1000.0)
        relative = (
            detector.robust_fractional_std
            + detector.calibration_uncertainty_fraction
            + 0.10 * timing_fraction
        )
        if window.evidence_kind == EvidenceKind.CUMULATIVE_RECOVERY:
            relative += 0.10
        return max(
            detector.robust_base_std_uSv_h,
            detector.robust_base_std_uSv_h + relative * max(0.0, observed_rate_uSv_h),
        )

    def _empty_prediction(self, at_time_ns: int, mode: str) -> MapPrediction:
        empty = np.full(self.grid.shape, np.nan)
        zeros = np.zeros(self.grid.shape)
        return MapPrediction(
            mission_id=self.mission_id,
            frame_id=self.world.frame_id,
            map_time_ns=at_time_ns,
            temporal_mode=mode,
            time_window_start_ns=None,
            time_window_end_ns=at_time_ns,
            x_coordinates_m=self.grid.x_coordinates_m.tolist(),
            y_coordinates_m=self.grid.y_coordinates_m.tolist(),
            values_row_major=_optional_float_list(empty),
            coverage_mask_row_major=np.zeros(self.grid.shape, dtype=bool).ravel().tolist(),
            p05_values_row_major=_optional_float_list(empty),
            p50_values_row_major=_optional_float_list(empty),
            p95_values_row_major=_optional_float_list(empty),
            uncertainty_values_row_major=_optional_float_list(empty),
            relative_uncertainty_row_major=_optional_float_list(empty),
            coverage_time_row_major=_optional_float_list(zeros),
            exposure_values_row_major=_optional_float_list(zeros),
            source_probability_row_major=_optional_float_list(zeros),
            probability_above_threshold_row_major=_optional_float_list(empty),
            distance_to_support_row_major=_optional_float_list(empty),
            model_fraction_row_major=_optional_float_list(zeros),
            residual_fraction_row_major=_optional_float_list(zeros),
            grid_shape=self.grid.shape,
            sample_count=0,
            interpolator="probabilistic_prior",
            exposure=self._combined_exposure(),
            layers=[
                "dose_rate",
                "uncertainty",
                "coverage",
                "exposure",
                "source_probability",
            ],
            metrics={"sample_count": 0, "coverage_percent": 0.0},
        )

    def _source_estimate(self) -> dict[str, object] | None:
        posterior = self.latest_posterior
        if posterior is None:
            return None
        x_m, y_m = posterior.posterior_map_x_y
        return {
            "x_m": x_m,
            "y_m": y_m,
            "strength_at_1m_uSv_h": posterior.posterior_median_strength_at_1m,
            "background_uSv_h": posterior.posterior_background,
            "confidence_radius_m": posterior.credible_regions["95"].conservative_radius_m,
            "credible_region_50": posterior.credible_regions["50"].model_dump(mode="json"),
            "credible_region_90": posterior.credible_regions["90"].model_dump(mode="json"),
            "credible_region_95": posterior.credible_regions["95"].model_dump(mode="json"),
            "p_source_exists": posterior.p_source_exists,
            "quality": posterior.identifiability_state.value,
            "detected": posterior.detected,
            "method": "regularized_particle_filter",
        }

    def _hotspot(self, values: np.ndarray) -> dict[str, float | None] | None:
        if not np.any(np.isfinite(values)):
            return None
        row, column = np.unravel_index(int(np.nanargmax(values)), values.shape)
        return {
            "x_m": float(self.grid.x_coordinates_m[column]),
            "y_m": float(self.grid.y_coordinates_m[row]),
            "estimated_uSv_h": float(values[row, column]),
            "maximum_observed_uSv_h": max(
                (sample.dose_rate_uSv_h_filtered for sample in self.samples),
                default=None,
            ),
            "distance_to_nearest_sample_m": None,
        }

    def _source_position_error(self) -> float | None:
        if self.field is None or self.latest_posterior is None:
            return None
        active = [source for source in self.field.sources if source.enabled]
        if len(active) != 1:
            return None
        truth = self.field.source_position(
            active[0],
            self.latest_posterior.map_time_ns / 1_000_000_000,
        )
        estimate = self.latest_posterior.posterior_map_x_y
        return float(np.hypot(estimate[0] - truth[0], estimate[1] - truth[1]))

    def _combined_exposure(self) -> ExposureSummary:
        summaries = [tracker.summary for tracker in self.exposure_trackers.values()]
        if not summaries:
            return ExposureSummary()
        return ExposureSummary(
            cumulative_detector_dose_uSv=sum(
                item.cumulative_detector_dose_uSv for item in summaries
            ),
            cumulative_robot_path_dose_uSv=sum(
                item.cumulative_robot_path_dose_uSv for item in summaries
            ),
            reported_cumulative_dose_uSv=sum(
                item.reported_cumulative_dose_uSv for item in summaries
            ) if all(item.reported_cumulative_dose_uSv is not None for item in summaries) else None,
            cumulative_closure_error_uSv=sum(
                item.cumulative_closure_error_uSv for item in summaries
            ),
            time_above_threshold_s=sum(item.time_above_threshold_s for item in summaries),
            recovered_gap_count=sum(item.recovered_gap_count for item in summaries),
            reset_count=sum(item.reset_count for item in summaries),
            audit_state=";".join(sorted({item.audit_state for item in summaries})),
        )

    def _detector_height(self) -> float:
        if self.observations:
            heights = [
                point.z_m for window in self.observations[-20:] for point in window.detector_path
            ]
            if heights:
                return float(np.median(heights))
        return 0.57

    @staticmethod
    def _append_bounded(items: list, value: object, limit: int = 5000) -> None:
        items.append(value)
        if len(items) > limit:
            del items[: len(items) - limit]

    @staticmethod
    def _append_latency(items: list[float], value: float) -> None:
        items.append(value)
        if len(items) > 2048:
            del items[: len(items) - 2048]

    @staticmethod
    def _percentile(values: list[float], percentile: float) -> float | None:
        return float(np.percentile(values, percentile)) if values else None


def _optional_float_list(values: np.ndarray) -> list[float | None]:
    return [float(value) if np.isfinite(value) else None for value in values.ravel()]
