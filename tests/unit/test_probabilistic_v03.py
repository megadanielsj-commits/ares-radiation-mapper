from __future__ import annotations

import math

import numpy as np
import pytest

from ares_mapper.config import (
    AdaptiveGridConfig,
    BoundsConfig,
    DetectorConfig,
    InferenceConfig,
    SensorTransformConfig,
    SynchronizationConfig,
    load_scenario,
)
from ares_mapper.core.synchronizer import TemporalSynchronizer
from ares_mapper.domain.enums import (
    EvidenceKind,
    IdentifiabilityState,
    MappingQuality,
    ObservationMode,
    Quality,
    SyncMethod,
)
from ares_mapper.domain.models import (
    DetectorPathPoint,
    MappedSample,
    ObservationWindow,
    PoseSample,
    RadiationSample,
)
from ares_mapper.fusion.trajectory import quadrature_weights
from ares_mapper.inference.identifiability import IdentifiabilityMonitor
from ares_mapper.inference.observation import RadiationObservationModel
from ares_mapper.inference.particle_filter import (
    RegularizedParticleFilter,
    effective_sample_size,
    normalize_log_weights,
    systematic_resample,
)
from ares_mapper.inference.source_existence import SourceExistenceModel
from ares_mapper.mapping.exposure import (
    MissionExposureTracker,
    recover_cumulative_gap,
)
from ares_mapper.mapping.quadtree import AdaptiveQuadtree
from ares_mapper.mapping.service import MapService


def _radiation(
    sequence: int,
    rate: float,
    *,
    start_ns: int,
    end_ns: int,
    cumulative: float = 0.0,
    cps: int | None = None,
) -> RadiationSample:
    return RadiationSample(
        mission_id="m",
        sensor_id="detector",
        sequence=sequence,
        time_domain_id="mission:m",
        timeline_time_ns=end_ns,
        source_time_ns=end_ns,
        received_utc_ns=end_ns,
        received_monotonic_ns=end_ns,
        effective_measurement_time_ns=(start_ns + end_ns) // 2,
        dose_rate_uSv_h=rate,
        cumulative_dose_uSv=cumulative,
        cps=cps,
        cpm=None if cps is None else cps * 60,
        integration_time_s=(end_ns - start_ns) / 1_000_000_000,
        integration_start_time_ns=start_ns,
        integration_end_time_ns=end_ns,
    )


def _window(
    sequence: int,
    x_m: float,
    y_m: float,
    rate: float,
    *,
    mode: ObservationMode = ObservationMode.DOSE_RATE_ROBUST,
    cps: int | None = None,
    cumulative: float = 0.0,
    evidence: EvidenceKind = EvidenceKind.INSTANTANEOUS,
) -> ObservationWindow:
    start_ns = (sequence - 1) * 1_000_000_000
    end_ns = sequence * 1_000_000_000
    sample = _radiation(
        sequence,
        rate,
        start_ns=start_ns,
        end_ns=end_ns,
        cumulative=cumulative,
        cps=cps,
    )
    return ObservationWindow(
        mission_id="m",
        sensor_id="detector",
        observation_sequence=sequence,
        radiation_sample=sample,
        detector_path=[
            DetectorPathPoint(
                timeline_time_ns=start_ns,
                x_m=x_m,
                y_m=y_m,
                z_m=0.57,
                position_std_m=0.05,
            ),
            DetectorPathPoint(
                timeline_time_ns=end_ns,
                x_m=x_m,
                y_m=y_m,
                z_m=0.57,
                position_std_m=0.05,
            ),
        ],
        path_time_weights_s=[0.5, 0.5],
        integration_start_ns=start_ns,
        integration_end_ns=end_ns,
        integration_time_s=1.0,
        maximum_pose_gap_ms=50.0,
        sync_error_ms=5.0,
        observation_mode=mode,
        evidence_kind=evidence,
    )


def _mapped(window: ObservationWindow) -> MappedSample:
    x_m, y_m, z_m = window.representative_xyz
    sample = window.radiation_sample
    return MappedSample(
        mission_id="m",
        mapped_sequence=window.observation_sequence,
        radiation_sequence=sample.sequence,
        sensor_id="detector",
        time_domain_id="mission:m",
        effective_measurement_time_ns=sample.effective_measurement_time_ns,
        frame_id="world",
        base_x_m=x_m,
        base_y_m=y_m,
        base_z_m=z_m - 0.25,
        sensor_x_m=x_m,
        sensor_y_m=y_m,
        sensor_z_m=z_m,
        sensor_yaw_rad=0.0,
        dose_rate_uSv_h_raw=sample.dose_rate_uSv_h,
        dose_rate_uSv_h_filtered=sample.dose_rate_uSv_h,
        cumulative_dose_uSv=sample.cumulative_dose_uSv,
        cps=sample.cps,
        cpm=sample.cpm,
        integration_time_s=window.integration_time_s,
        integration_start_time_ns=window.integration_start_ns,
        integration_end_time_ns=window.integration_end_ns,
        sync_method=SyncMethod.EXACT,
        max_pose_gap_ms=window.maximum_pose_gap_ms,
        sync_error_estimate_ms=window.sync_error_ms,
        pose_quality=Quality.VALID,
        radiation_quality=Quality.VALID,
        mapping_quality=MappingQuality.VALID,
    )


def test_irregular_quadrature_preserves_exact_duration() -> None:
    weights = quadrature_weights([0, 100_000_000, 400_000_000, 1_000_000_000])
    assert weights == pytest.approx([0.05, 0.2, 0.45, 0.3])
    assert sum(weights) == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("separation_m", "expected"),
    [(0.04, IdentifiabilityState.STABLE), (1.0, IdentifiabilityState.MULTIMODAL)],
)
def test_localization_peaks_need_physical_separation(
    separation_m: float, expected: IdentifiabilityState
) -> None:
    monitor = IdentifiabilityMonitor(InferenceConfig(), cell_size_m=.25)
    for sequence, angle in enumerate(np.linspace(0, 2 * math.pi, 8, endpoint=False), 1):
        monitor.add(_window(sequence, 5 + 3 * math.cos(angle), 5 + 3 * math.sin(angle), 1), .1)
    rng = np.random.default_rng(42)
    particles = np.concatenate([
        rng.normal((5 - separation_m / 2, 5), .0005, (1000, 2)),
        rng.normal((5 + separation_m / 2, 5), .0005, (1000, 2)),
    ])
    state, diagnostics = monitor.evaluate(
        particles, np.full(2000, 1 / 2000), (5, 5), .1, .999
    )
    assert state == expected
    assert diagnostics["multimodal"] == (expected == IdentifiabilityState.MULTIMODAL)


def test_log_weight_normalization_and_ess_are_finite() -> None:
    normalized, evidence = normalize_log_weights(np.asarray([-1000.0, -1001.0]))
    assert np.isfinite(normalized).all()
    assert math.isfinite(evidence)
    assert np.sum(np.exp(normalized)) == pytest.approx(1.0)
    assert 1.0 <= effective_sample_size(normalized) <= 2.0


def test_systematic_resampling_is_deterministic_for_seed() -> None:
    weights = np.asarray([0.05, 0.15, 0.30, 0.50])
    first = systematic_resample(weights, np.random.default_rng(7))
    second = systematic_resample(weights, np.random.default_rng(7))
    assert np.array_equal(first, second)
    assert np.all((first >= 0) & (first < len(weights)))


def test_poisson_likelihood_matches_closed_form() -> None:
    detector = DetectorConfig(
        sensor_id="detector",
        observation_mode="counts_poisson",
        sensitivity_cps_per_uSv_h=10.0,
    )
    model = RadiationObservationModel(
        {"detector": detector},
        source_z_m=0.0,
        minimum_distance_m=0.25,
    )
    window = _window(
        1,
        0.0,
        0.0,
        1.0,
        mode=ObservationMode.COUNTS_POISSON,
        cps=10,
    )
    particles = np.asarray([[10.0, 10.0, math.log(0.01), math.log(1.0)]])
    result = model.log_likelihood_h1(particles, window)[0]
    expected_mean = model.expected_rate(particles, window)[0] * 10.0
    expected = 10 * math.log(expected_mean) - expected_mean - math.lgamma(11)
    assert result == pytest.approx(expected)


def test_source_existence_uses_separate_model_evidence() -> None:
    existence = SourceExistenceModel(0.5)
    assert existence.update(2.0, 0.0) > 0.5
    assert existence.update(-5.0, 0.0) < 0.5


def test_particle_filter_recovers_simple_source_without_truth_input() -> None:
    detector = DetectorConfig(
        sensor_id="detector",
        robust_base_std_uSv_h=0.01,
        robust_fractional_std=0.02,
        calibration_uncertainty_fraction=0.01,
    )
    inference = InferenceConfig(
        particles=1024,
        render_particles=128,
        source_strength_max_uSv_h=20.0,
        background_prior_uSv_h=0.15,
        stable_radius_95_m=1.0,
    )
    particle_filter = RegularizedParticleFilter(
        "m",
        BoundsConfig(x_min=0, x_max=10, y_min=0, y_max=10),
        {"detector": detector},
        inference,
        AdaptiveGridConfig(),
        minimum_distance_m=0.25,
        background_uSv_h=0.15,
        seed=19,
    )
    positions = [
        (1, 1),
        (5, 1),
        (9, 1),
        (9, 5),
        (9, 9),
        (5, 9),
        (1, 9),
        (1, 5),
        (4, 4),
        (6, 4),
        (6, 6),
        (4, 6),
    ]
    posterior = None
    for sequence, (x_m, y_m) in enumerate(positions, 1):
        distance_sq = (x_m - 5.0) ** 2 + (y_m - 5.0) ** 2 + 0.57**2
        posterior = particle_filter.update(_window(sequence, x_m, y_m, 0.15 + 5.0 / distance_sq))
    assert posterior is not None
    assert math.dist(posterior.posterior_mean_x_y, (5.0, 5.0)) < 0.5
    assert posterior.p_source_exists > 0.95
    assert np.isfinite(particle_filter.log_weights).all()
    assert np.sum(particle_filter.weights) == pytest.approx(1.0)


def test_pure_background_does_not_produce_stable_detection() -> None:
    detector = DetectorConfig(sensor_id="detector")
    inference = InferenceConfig(particles=512, render_particles=64)
    particle_filter = RegularizedParticleFilter(
        "m",
        BoundsConfig(x_min=0, x_max=10, y_min=0, y_max=10),
        {"detector": detector},
        inference,
        AdaptiveGridConfig(),
        minimum_distance_m=0.25,
        background_uSv_h=0.15,
        seed=31,
    )
    posterior = None
    for sequence, angle in enumerate(np.linspace(0, 2 * math.pi, 16), 1):
        posterior = particle_filter.update(
            _window(
                sequence,
                5.0 + 4.0 * math.cos(float(angle)),
                5.0 + 4.0 * math.sin(float(angle)),
                0.15,
            )
        )
    assert posterior is not None
    assert not posterior.detected
    assert posterior.identifiability_state != IdentifiabilityState.STABLE


def test_quadtree_splits_and_merges_with_hysteresis() -> None:
    config = AdaptiveGridConfig(
        far_cell_m=2.0,
        default_cell_m=1.0,
        near_cell_m=0.5,
        minimum_cell_m=0.5,
        merge_hysteresis_updates=2,
    )
    tree = AdaptiveQuadtree(
        BoundsConfig(x_min=0, x_max=4, y_min=0, y_max=4),
        config,
    )
    tree.update(lambda node: (node.size_m > 0.5, ["TEST"], 0.5), 0.5)
    assert len(tree.leaves()) == 64
    tree.update(lambda node: (False, [], 2.0), 0.5)
    assert len(tree.leaves()) > 1
    tree.update(lambda node: (False, [], 2.0), 0.5)
    assert len(tree.leaves()) == 1


def test_cumulative_dose_recovers_only_missing_interval() -> None:
    previous = _radiation(
        1,
        1.0,
        start_ns=0,
        end_ns=1_000_000_000,
        cumulative=0.00,
    )
    current = _radiation(
        3,
        1.0,
        start_ns=2_000_000_000,
        end_ns=3_000_000_000,
        cumulative=0.02,
    )
    recovery = recover_cumulative_gap(previous, current, 0.01)
    assert recovery is not None
    assert recovery.start_ns == 1_000_000_000
    assert recovery.end_ns == 2_000_000_000
    assert recovery.dose_uSv == pytest.approx(0.02 - 1 / 3600)
    assert recovery.rate_uncertainty_uSv_h > 0


def test_cumulative_dose_is_audit_only_when_no_packet_is_missing() -> None:
    first = _window(1, 1, 1, 1.0, cumulative=0.0)
    second = _window(2, 1, 1, 1.0, cumulative=0.0)
    tracker = MissionExposureTracker(0.01)
    tracker.update(first)
    audit = tracker.update(second)
    assert audit.recovered_rate_uSv_h is None
    assert tracker.summary.recovered_gap_count == 0


def test_correlated_fs5000_fields_create_one_posterior_update() -> None:
    scenario = load_scenario("config/scenarios/static_source.yaml")
    scenario.inference.particles = 256
    scenario.inference.render_particles = 32
    service = MapService(
        "m",
        scenario.world,
        scenario.mapping,
        inference=scenario.inference,
        grid_config=scenario.grid,
        residual_config=scenario.residual,
        detectors=[DetectorConfig(sensor_id="detector")],
        seed=5,
    )
    window = _window(1, 1.0, 1.0, 0.2, cps=1, cumulative=0.01)
    window.radiation_sample.cpm = 60
    window.radiation_sample.average_dose_rate_uSv_h = 0.2
    update = service.add_observation(window, _mapped(window))
    assert update.posterior.update_sequence == 1
    assert service.raw_observation_count == 1


def test_truth_namespace_is_removed_before_inference() -> None:
    sync = TemporalSynchronizer(
        SynchronizationConfig(max_pose_gap_ms=1500.0),
        {"detector": SensorTransformConfig()},
    )
    for sequence, time_ns in enumerate((0, 1_000_000_000), 1):
        sync.add_pose(
            PoseSample(
                mission_id="m",
                source_id="pose",
                sequence=sequence,
                time_domain_id="mission:m",
                timeline_time_ns=time_ns,
                received_utc_ns=time_ns,
                received_monotonic_ns=time_ns,
                x_m=float(sequence),
                y_m=0.0,
                z_m=0.32,
                truth_x_m=99.0,
                truth_y_m=99.0,
                is_ground_truth=False,
            )
        )
    sample = _radiation(
        1,
        1.0,
        start_ns=0,
        end_ns=1_000_000_000,
    ).model_copy(
        update={
            "true_dose_rate_uSv_h": 999.0,
            "true_sensor_x_m": 999.0,
            "true_sensor_y_m": 999.0,
        }
    )
    window = sync.build_observation_window(sample)
    assert window is not None
    assert window.radiation_sample.true_dose_rate_uSv_h is None
    assert all(point.x_m != 99.0 for point in window.detector_path)


def test_render_resolution_does_not_change_posterior_or_raw_count() -> None:
    scenario = load_scenario("config/scenarios/static_source.yaml")
    scenario.inference.particles = 256
    scenario.inference.render_particles = 32
    detector = DetectorConfig(sensor_id="detector")
    first_mapping = scenario.mapping.model_copy(update={"grid_resolution_m": 0.5})
    second_mapping = scenario.mapping.model_copy(update={"grid_resolution_m": 1.0})
    services = [
        MapService(
            "m",
            scenario.world,
            mapping,
            inference=scenario.inference,
            grid_config=scenario.grid,
            residual_config=scenario.residual,
            detectors=[detector],
            seed=11,
        )
        for mapping in (first_mapping, second_mapping)
    ]
    window = _window(1, 2.0, 2.0, 0.3)
    for service in services:
        service.add_observation(window, _mapped(window))
        service.predict(1_000_000_000)
    assert services[0].raw_observation_count == services[1].raw_observation_count == 1
    assert (
        services[0].latest_posterior.posterior_mean_x_y  # type: ignore[union-attr]
        == services[1].latest_posterior.posterior_mean_x_y  # type: ignore[union-attr]
    )


def test_map_predictions_are_non_negative_and_separate_layers() -> None:
    scenario = load_scenario("config/scenarios/static_source.yaml")
    scenario.inference.particles = 256
    scenario.inference.render_particles = 32
    detector = DetectorConfig(sensor_id="detector")
    service = MapService(
        "m",
        scenario.world,
        scenario.mapping,
        inference=scenario.inference,
        grid_config=scenario.grid,
        residual_config=scenario.residual,
        detectors=[detector],
    )
    window = _window(1, 2.0, 2.0, 0.3)
    service.add_observation(window, _mapped(window))
    prediction = service.predict(1_000_000_000)
    assert all(value is None or value >= 0 for value in prediction.values_row_major)
    assert {
        "dose_rate",
        "uncertainty",
        "coverage",
        "exposure",
        "source_probability",
    }.issubset(prediction.layers)
    assert len(prediction.values_row_major) == len(prediction.coverage_mask_row_major)
