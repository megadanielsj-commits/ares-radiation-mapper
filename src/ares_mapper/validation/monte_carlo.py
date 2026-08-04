"""Monte Carlo acceptance harness for the probabilistic reconstruction."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

import numpy as np

from ares_mapper.config import ScenarioConfig
from ares_mapper.core.transforms import apply_sensor_transform
from ares_mapper.domain.enums import (
    EvidenceKind,
    IdentifiabilityState,
    ObservationMode,
    Quality,
)
from ares_mapper.domain.models import (
    DetectorPathPoint,
    ObservationWindow,
    RadiationSample,
    SourcePosterior,
)
from ares_mapper.fusion.trajectory import quadrature_weights
from ares_mapper.inference.particle_filter import RegularizedParticleFilter
from ares_mapper.simulation.detector import DetectorModel
from ares_mapper.simulation.radiation_field import RadiationField
from ares_mapper.simulation.trajectory import Trajectory


@dataclass(frozen=True, slots=True)
class TrialResult:
    source_present: bool
    source_position_error_m: float | None
    source_strength_relative_error: float | None
    background_error_uSv_h: float
    truth_in_95_region: bool | None
    detected: bool
    p_source_exists: float
    time_to_stable_s: float | None
    posterior_update_latency_p95_ms: float
    final_posterior: SourcePosterior


@dataclass(frozen=True, slots=True)
class ValidationReport:
    schema_version: str
    source_trials: int
    background_trials: int
    measurements_per_trial: int
    median_source_position_error_m: float
    median_source_strength_relative_error: float
    credible_region_coverage_95: float
    false_positive_rate: float
    median_background_error_uSv_h: float
    median_time_to_stable_s: float | None
    posterior_update_latency_p95_ms: float
    acceptance: dict[str, bool]

    @property
    def passed(self) -> bool:
        return all(self.acceptance.values())

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source_trials": self.source_trials,
            "background_trials": self.background_trials,
            "measurements_per_trial": self.measurements_per_trial,
            "median_source_position_error_m": self.median_source_position_error_m,
            "median_source_strength_relative_error": (self.median_source_strength_relative_error),
            "credible_region_coverage_95": self.credible_region_coverage_95,
            "false_positive_rate": self.false_positive_rate,
            "median_background_error_uSv_h": self.median_background_error_uSv_h,
            "median_time_to_stable_s": self.median_time_to_stable_s,
            "posterior_update_latency_p95_ms": (self.posterior_update_latency_p95_ms),
            "acceptance": self.acceptance,
            "passed": self.passed,
        }


def run_reference_validation(
    scenario: ScenarioConfig,
    *,
    source_trials: int = 100,
    background_trials: int = 100,
) -> ValidationReport:
    """Run the V0.3 reference trial and its pure-background control."""

    source_results = [
        _run_trial(scenario, scenario.mission.seed + 10_007 * index, True)
        for index in range(source_trials)
    ]
    background_results = [
        _run_trial(scenario, scenario.mission.seed + 20_011 * index + 1, False)
        for index in range(background_trials)
    ]
    errors = [
        float(result.source_position_error_m)
        for result in source_results
        if result.source_position_error_m is not None
    ]
    strength_errors = [
        float(result.source_strength_relative_error)
        for result in source_results
        if result.source_strength_relative_error is not None
    ]
    coverage = float(
        np.mean(
            [
                bool(result.truth_in_95_region)
                for result in source_results
                if result.truth_in_95_region is not None
            ]
        )
    )
    false_positive = float(np.mean([result.detected for result in background_results]))
    background_errors = [
        result.background_error_uSv_h for result in (*source_results, *background_results)
    ]
    stable_times = [
        result.time_to_stable_s for result in source_results if result.time_to_stable_s is not None
    ]
    latencies = [
        result.posterior_update_latency_p95_ms for result in (*source_results, *background_results)
    ]
    median_error = float(np.median(errors))
    latency_p95 = float(np.percentile(latencies, 95))
    acceptance = {
        "median_source_position_error_lte_0_5m": median_error <= 0.5,
        "credible_95_coverage_between_0_90_and_0_98": 0.90 <= coverage <= 0.98,
        "false_positive_rate_lt_0_05": false_positive < 0.05,
        "posterior_update_p95_lt_50ms": latency_p95 < 50.0,
    }
    return ValidationReport(
        schema_version="1.1",
        source_trials=source_trials,
        background_trials=background_trials,
        measurements_per_trial=int(
            scenario.mission.duration_s
            * max(detector.publish_rate_hz for detector in scenario.detectors)
        ),
        median_source_position_error_m=median_error,
        median_source_strength_relative_error=float(np.median(strength_errors)),
        credible_region_coverage_95=coverage,
        false_positive_rate=false_positive,
        median_background_error_uSv_h=float(np.median(background_errors)),
        median_time_to_stable_s=(float(np.median(stable_times)) if stable_times else None),
        posterior_update_latency_p95_ms=latency_p95,
        acceptance=acceptance,
    )


def _run_trial(
    scenario: ScenarioConfig,
    seed: int,
    source_present: bool,
) -> TrialResult:
    detector = scenario.detectors[0].model_copy(deep=True)
    rng = np.random.Generator(np.random.PCG64(seed + 307))
    detector_model = DetectorModel(detector, rng)
    trajectory = Trajectory(
        scenario.trajectory,
        scenario.world,
        seed,
        scenario.mission.duration_s,
    )
    sources = (
        [source.model_copy(deep=True) for source in scenario.radiation_sources]
        if source_present
        else []
    )
    field = RadiationField(scenario.world, sources)
    particle_filter = RegularizedParticleFilter(
        f"validation-{seed}",
        scenario.world.bounds_m,
        {detector.sensor_id: detector},
        scenario.inference,
        scenario.grid,
        minimum_distance_m=scenario.mapping.source_minimum_distance_m,
        background_uSv_h=scenario.world.background.dose_rate_uSv_h,
        seed=seed,
    )
    period_s = 1.0 / detector.publish_rate_hz
    measurements = int(math.floor(scenario.mission.duration_s * detector.publish_rate_hz + 1e-9))
    stable_at: float | None = None
    latencies_ms: list[float] = []
    posterior: SourcePosterior | None = None
    for sequence in range(1, measurements + 1):
        end_s = sequence * period_s
        start_s = end_s - period_s
        point_count = max(2, int(round(scenario.odometry.publish_rate_hz * period_s)) + 1)
        times_s = np.linspace(start_s, end_s, point_count)
        times_ns = [int(round(value * 1_000_000_000)) for value in times_s]
        weights_s = quadrature_weights(times_ns)
        truth_sensor_states: list[tuple[float, float, float, float]] = []
        observed_path: list[DetectorPathPoint] = []
        for time_s, timeline_ns in zip(times_s, times_ns, strict=True):
            truth = trajectory.pose_at(float(time_s))
            truth_sensor_states.append(
                apply_sensor_transform(
                    truth.x_m,
                    truth.y_m,
                    truth.z_m,
                    truth.yaw_rad,
                    detector.transform_base_sensor,
                )
            )
            observed_sensor = apply_sensor_transform(
                truth.x_m + float(rng.normal(0.0, scenario.odometry.position_noise_std_m)),
                truth.y_m + float(rng.normal(0.0, scenario.odometry.position_noise_std_m)),
                truth.z_m,
                truth.yaw_rad + float(rng.normal(0.0, scenario.odometry.yaw_noise_std_rad)),
                detector.transform_base_sensor,
            )
            observed_path.append(
                DetectorPathPoint(
                    timeline_time_ns=timeline_ns,
                    x_m=observed_sensor[0],
                    y_m=observed_sensor[1],
                    z_m=observed_sensor[2],
                    yaw_rad=observed_sensor[3],
                    position_std_m=scenario.odometry.position_noise_std_m,
                    time_uncertainty_ns=int(max(0.0, scenario.odometry.jitter_ms_std) * 1_000_000),
                )
            )
        true_rates = np.asarray(
            [
                field.dose_rate(x_m, y_m, z_m, float(time_s))
                for (x_m, y_m, z_m, _), time_s in zip(truth_sensor_states, times_s, strict=True)
            ],
            dtype=float,
        )
        true_rate = float(np.average(true_rates, weights=np.asarray(weights_s, dtype=float)))
        reading = detector_model.measure(true_rate, period_s)
        end_ns = times_ns[-1]
        start_ns = times_ns[0]
        sample = RadiationSample(
            mission_id=f"validation-{seed}",
            sensor_id=detector.sensor_id,
            sequence=sequence,
            time_domain_id=f"validation:{seed}",
            timeline_time_ns=end_ns,
            source_time_ns=end_ns,
            received_utc_ns=end_ns,
            received_monotonic_ns=end_ns,
            time_uncertainty_ns=int(detector.jitter_ms_std * 1_000_000),
            effective_measurement_time_ns=(start_ns + end_ns) // 2,
            dose_rate_uSv_h=reading.dose_rate_uSv_h,
            cumulative_dose_uSv=reading.cumulative_dose_uSv,
            cps=reading.cps,
            cpm=reading.cpm,
            average_dose_rate_uSv_h=reading.average_dose_rate_uSv_h,
            integration_time_s=period_s,
            integration_start_time_ns=start_ns,
            integration_end_time_ns=end_ns,
            quality=reading.quality,
            calibration_id=detector.calibration_id,
            alarm=reading.alarm,
        )
        window = ObservationWindow(
            mission_id=sample.mission_id,
            sensor_id=sample.sensor_id,
            observation_sequence=sequence,
            radiation_sample=sample,
            detector_path=observed_path,
            path_time_weights_s=weights_s,
            integration_start_ns=start_ns,
            integration_end_ns=end_ns,
            integration_time_s=period_s,
            maximum_pose_gap_ms=1000.0 / scenario.odometry.publish_rate_hz,
            sync_error_ms=max(
                scenario.odometry.jitter_ms_std,
                detector.jitter_ms_std,
            ),
            observation_mode=ObservationMode(detector.observation_mode),
            evidence_kind=EvidenceKind.INSTANTANEOUS,
            quality=Quality.VALID,
        )
        started = time.perf_counter_ns()
        posterior = particle_filter.update(window)
        latencies_ms.append((time.perf_counter_ns() - started) / 1_000_000.0)
        if stable_at is None and posterior.identifiability_state == IdentifiabilityState.STABLE:
            stable_at = end_s
    if posterior is None:
        raise RuntimeError("validation scenario produced no observations")
    background_truth = scenario.world.background.dose_rate_uSv_h
    if source_present:
        source = scenario.radiation_sources[0]
        source_truth = field.source_position(source, scenario.mission.duration_s)
        strength_truth = field.source_strength(source, scenario.mission.duration_s)
        position_error = math.hypot(
            posterior.posterior_mean_x_y[0] - source_truth[0],
            posterior.posterior_mean_x_y[1] - source_truth[1],
        )
        strength_error = abs(posterior.posterior_median_strength_at_1m - strength_truth) / max(
            strength_truth, 1e-12
        )
        inside = position_error <= posterior.credible_regions["95"].conservative_radius_m
    else:
        position_error = None
        strength_error = None
        inside = None
    return TrialResult(
        source_present=source_present,
        source_position_error_m=position_error,
        source_strength_relative_error=strength_error,
        background_error_uSv_h=abs(posterior.posterior_background - background_truth),
        truth_in_95_region=inside,
        detected=posterior.detected,
        p_source_exists=posterior.p_source_exists,
        time_to_stable_s=stable_at,
        posterior_update_latency_p95_ms=float(np.percentile(latencies_ms, 95)),
        final_posterior=posterior,
    )
