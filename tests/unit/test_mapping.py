import numpy as np
import pytest

from ares_mapper.config import ResidualConfig, load_scenario
from ares_mapper.domain.enums import (
    IdentifiabilityState,
    MappingQuality,
    Quality,
    SyncMethod,
)
from ares_mapper.domain.models import MappedSample
from ares_mapper.mapping.fusion import fit_single_point_source
from ares_mapper.mapping.grid import GridSpec
from ares_mapper.mapping.idw import interpolate
from ares_mapper.mapping.residual import ResidualIDW
from ares_mapper.mapping.service import MapService


def sample(sequence: int, x_m: float, y_m: float, value: float, time_ns: int) -> MappedSample:
    return MappedSample(
        mission_id="m",
        mapped_sequence=sequence,
        radiation_sequence=sequence,
        sensor_id="detector",
        time_domain_id="sim:m",
        effective_measurement_time_ns=time_ns,
        frame_id="world",
        base_x_m=x_m,
        base_y_m=y_m,
        base_z_m=0.32,
        sensor_x_m=x_m,
        sensor_y_m=y_m,
        sensor_z_m=0.57,
        sensor_yaw_rad=0,
        dose_rate_uSv_h_raw=value,
        dose_rate_uSv_h_filtered=value,
        sync_method=SyncMethod.EXACT,
        max_pose_gap_ms=0,
        sync_error_estimate_ms=0,
        pose_quality=Quality.VALID,
        radiation_quality=Quality.VALID,
        mapping_quality=MappingQuality.VALID,
    )


def test_idw_exact_point_returns_observation_mean() -> None:
    result = interpolate(
        np.asarray([[1.0, 1.0]]),
        np.asarray([[1.0, 1.0], [1.0, 1.0], [2.0, 2.0]]),
        np.asarray([1.0, 3.0, 9.0]),
        np.asarray([0, 0, 0]),
        at_time_ns=0,
        power=2,
        epsilon_m=0.02,
        influence_radius_m=5,
        maximum_neighbors=10,
    )
    assert result[0] == pytest.approx(2.0)


def test_early_gradient_stays_local_and_bounded_by_measurement() -> None:
    scenario = load_scenario("config/scenarios/static_source.yaml")
    scenario.mapping.grid_resolution_m = 1.0
    scenario.mapping.influence_radius_m = 0.4
    scenario.mapping.coverage_mode = "radius"
    service = MapService("m", scenario.world, scenario.mapping)
    service.add_sample(sample(1, 1, 1, 0.5, 0))
    prediction = service.predict(0)
    assert prediction.sample_count == 1
    finite = [value for value in prediction.values_row_major if value is not None]
    assert finite
    assert max(finite) <= 0.5 + 1e-9
    assert any(value is None for value in prediction.values_row_major)
    assert any(not covered for covered in prediction.coverage_mask_row_major)
    assert prediction.source_estimate is None
    assert prediction.metrics["reconstruction_mode"] == "measured_local"


def test_local_gradient_never_exceeds_configured_support_radius() -> None:
    scenario = load_scenario("config/scenarios/static_source.yaml")
    service = MapService(
        "m",
        scenario.world,
        scenario.mapping,
        inference=scenario.inference,
        grid_config=scenario.grid,
        residual_config=scenario.residual,
        detectors=scenario.detectors,
    )
    service.add_sample(sample(1, 2.0, 2.0, 50.0, 0))
    prediction = service.predict(0)
    support_points, _, _, _ = service.observation_grid.support_arrays()
    finite_points = [
        (x_m, y_m)
        for row, y_m in enumerate(prediction.y_coordinates_m)
        for column, x_m in enumerate(prediction.x_coordinates_m)
        if prediction.values_row_major[row * len(prediction.x_coordinates_m) + column] is not None
    ]
    assert finite_points
    assert all(
        min(np.linalg.norm(np.asarray(point) - support_points, axis=1))
        < scenario.mapping.influence_radius_m
        for point in finite_points
    )


def test_distant_measurement_does_not_repaint_previous_local_region() -> None:
    scenario = load_scenario("config/scenarios/static_source.yaml")
    service = MapService(
        "m",
        scenario.world,
        scenario.mapping,
        inference=scenario.inference,
        grid_config=scenario.grid,
        residual_config=scenario.residual,
        detectors=scenario.detectors,
    )
    service.add_sample(sample(1, 1.0, 1.0, 1.0, 0))
    before = service.predict(0)
    target_index = before.y_coordinates_m.index(1.0) * len(
        before.x_coordinates_m
    ) + before.x_coordinates_m.index(1.0)
    previous_value = before.values_row_major[target_index]
    service.add_sample(sample(2, 3.0, 1.0, 100.0, 1_000_000_000))
    after = service.predict(1_000_000_000)
    assert previous_value is not None
    assert after.values_row_major[target_index] == pytest.approx(previous_value)


def test_high_rate_measurement_uncertainty_scales_with_the_rate() -> None:
    scenario = load_scenario("config/scenarios/static_source.yaml")
    service = MapService("m", scenario.world, scenario.mapping)
    service.add_sample(sample(1, 2.0, 2.0, 100_000.0, 0))
    _, _, variances, _ = service.observation_grid.support_arrays()
    assert len(variances) == 1
    assert np.sqrt(variances[0]) >= 0.20 * 100_000.0


def test_residual_support_does_not_expand_with_quadtree_cell_size() -> None:
    residual = ResidualIDW(
        ResidualConfig(maximum_support_cells=3.0),
        observation_cell_m=0.25,
    )
    means, variances, _ = residual.predict(
        np.asarray([[0.0, 0.0], [2.0, 0.0]]),
        np.asarray([[0.0, 0.0]]),
        np.asarray([10.0]),
        np.asarray([0.04]),
        np.asarray([2.0, 2.0]),
    )
    assert means[0] == pytest.approx(10.0)
    assert means[1] == pytest.approx(0.0)
    assert variances[1] <= 1e-9


def test_robust_global_field_ignores_small_high_intensity_particle_tail() -> None:
    scenario = load_scenario("config/scenarios/static_source.yaml")
    scenario.inference = scenario.inference.model_copy(
        update={
            "particles": 1000,
            "render_particles": 128,
            "source_strength_min_uSv_h": 1_000.0,
            "source_strength_max_uSv_h": 10_000_000.0,
        }
    )
    service = MapService(
        "m",
        scenario.world,
        scenario.mapping,
        inference=scenario.inference,
        grid_config=scenario.grid,
        residual_config=scenario.residual,
        detectors=scenario.detectors,
    )
    particles = service.particle_filter.particles
    particles[:980, 0] = 5.0
    particles[:980, 1] = 5.0
    particles[:980, 2] = np.log(100_000.0)
    particles[:980, 3] = np.log(0.1)
    particles[980:, 0] = 0.0
    particles[980:, 1] = 0.0
    particles[980:, 2] = np.log(10_000_000.0)
    particles[980:, 3] = np.log(0.1)
    service.particle_filter.log_weights.fill(-np.log(len(particles)))

    values = service.reconstructor._robust_physical_center(  # noqa: SLF001
        np.asarray([[5.0, 5.0], [0.0, 0.0]]),
        detector_height_m=0.57,
    )
    expected_far = 0.1 + 100_000.0 / (5.0**2 + 5.0**2 + (0.8 - 0.57) ** 2)
    assert values[0] > 1_000_000.0
    assert values[1] == pytest.approx(expected_far)
    assert values[1] < 5_000.0


def test_global_field_is_revoked_as_soon_as_posterior_is_not_stable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = load_scenario("config/scenarios/static_source.yaml")
    scenario.mapping.global_model_stable_updates = 2
    scenario.mapping.global_model_transition_updates = 1
    scenario.mapping.global_model_unstable_grace_updates = 0
    service = MapService(
        "m",
        scenario.world,
        scenario.mapping,
        inference=scenario.inference,
        grid_config=scenario.grid,
        residual_config=scenario.residual,
        detectors=scenario.detectors,
    )
    service.add_sample(sample(1, 1.0, 1.0, 1.0, 1_000_000_000))
    base = service.latest_posterior
    assert base is not None
    stable = base.model_copy(
        update={
            "detected": True,
            "identifiability_state": IdentifiabilityState.STABLE,
        }
    )
    unstable = base.model_copy(
        update={
            "detected": False,
            "identifiability_state": IdentifiabilityState.MULTIMODAL,
        }
    )
    monkeypatch.setattr(service.particle_filter, "update", lambda window: stable)
    service.add_sample(sample(2, 2.0, 1.0, 2.0, 2_000_000_000))
    service.add_sample(sample(3, 3.0, 1.0, 3.0, 3_000_000_000))
    assert service.predict(3_000_000_000).metrics["global_model_ready"] is True

    monkeypatch.setattr(service.particle_filter, "update", lambda window: unstable)
    service.add_sample(sample(4, 4.0, 1.0, 4.0, 4_000_000_000))
    prediction = service.predict(4_000_000_000)
    assert prediction.metrics["global_model_ready"] is False
    assert prediction.metrics["reconstruction_mode"] == "measured_local"


def test_global_field_fades_in_over_multiple_stable_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = load_scenario("config/scenarios/static_source.yaml")
    scenario.mapping.global_model_stable_updates = 2
    scenario.mapping.global_model_transition_updates = 4
    service = MapService(
        "m",
        scenario.world,
        scenario.mapping,
        inference=scenario.inference,
        grid_config=scenario.grid,
        residual_config=scenario.residual,
        detectors=scenario.detectors,
    )
    service.add_sample(sample(1, 1.0, 1.0, 1.0, 1_000_000_000))
    base = service.latest_posterior
    assert base is not None
    stable = base.model_copy(
        update={
            "detected": True,
            "identifiability_state": IdentifiabilityState.STABLE,
        }
    )
    monkeypatch.setattr(service.particle_filter, "update", lambda window: stable)

    service.add_sample(sample(2, 2.0, 1.0, 2.0, 2_000_000_000))
    service.add_sample(sample(3, 3.0, 1.0, 3.0, 3_000_000_000))
    first_global = service.predict(3_000_000_000)
    assert first_global.metrics["reconstruction_mode"] == "physical_transition"
    assert first_global.metrics["global_model_blend"] == pytest.approx(0.25)

    for sequence in range(4, 7):
        service.add_sample(
            sample(
                sequence,
                float(sequence),
                1.0,
                float(sequence),
                sequence * 1_000_000_000,
            )
        )
    completed = service.predict(6_000_000_000)
    assert completed.metrics["reconstruction_mode"] == "physical_global"
    assert completed.metrics["global_model_blend"] == pytest.approx(1.0)


def test_grid_respects_bounds() -> None:
    scenario = load_scenario("config/scenarios/static_source.yaml")
    grid = GridSpec.from_bounds(scenario.world.bounds_m, 0.5)
    assert grid.x_coordinates_m[0] == scenario.world.bounds_m.x_min
    assert grid.x_coordinates_m[-1] == scenario.world.bounds_m.x_max
    assert grid.y_coordinates_m[-1] == scenario.world.bounds_m.y_max


def test_weighted_source_fit_recovers_inverse_square_source() -> None:
    scenario = load_scenario("config/scenarios/static_source.yaml")
    source_x = 7.0
    source_y = 5.0
    strength = 2.0
    background = 0.1
    positions = [
        (1.0, 1.0),
        (2.0, 1.0),
        (3.0, 1.5),
        (4.0, 2.0),
        (5.0, 2.5),
        (6.0, 3.0),
        (6.5, 4.0),
        (5.5, 5.5),
        (4.0, 6.0),
        (2.0, 5.0),
    ]
    samples = []
    cumulative = 0.0
    for index, (x_m, y_m) in enumerate(positions, start=1):
        distance = max(0.25, np.hypot(x_m - source_x, y_m - source_y))
        value = background + strength / distance**2
        cumulative += value / 3600.0
        item = sample(index, x_m, y_m, value, index * 1_000_000_000)
        samples.append(
            item.model_copy(
                update={
                    "cpm": max(1, round(value * 157)),
                    "integration_time_s": 1.0,
                    "cumulative_dose_uSv": cumulative,
                }
            )
        )
    estimate, _ = fit_single_point_source(samples, scenario.world.bounds_m)
    assert estimate is not None
    assert estimate.x_m == pytest.approx(source_x, abs=0.15)
    assert estimate.y_m == pytest.approx(source_y, abs=0.15)
    assert estimate.strength_at_1m_uSv_h == pytest.approx(strength, rel=0.15)


def test_hybrid_map_updates_the_global_field_after_source_fit() -> None:
    scenario = load_scenario("config/scenarios/static_source.yaml")
    scenario.mapping.grid_resolution_m = 1.0
    scenario.mapping.global_model_transition_updates = 1
    scenario.inference.particles = 1024
    scenario.inference.render_particles = 128
    service = MapService(
        "m",
        scenario.world,
        scenario.mapping,
        inference=scenario.inference,
        grid_config=scenario.grid,
        residual_config=scenario.residual,
        detectors=scenario.detectors,
        seed=19,
    )
    source_x, source_y, strength, background = 7.0, 5.0, 2.0, 0.1
    positions = [
        (1.0, 1.0),
        (5.0, 1.0),
        (9.0, 1.0),
        (9.0, 5.0),
        (9.0, 7.0),
        (5.0, 7.0),
        (1.0, 7.0),
        (1.0, 5.0),
        (4.0, 4.0),
        (6.0, 4.0),
        (6.0, 6.0),
        (4.0, 6.0),
        (7.0, 4.5),
        (7.5, 5.0),
        (7.0, 5.5),
        (6.5, 5.0),
    ]
    for index, (x_m, y_m) in enumerate(positions, start=1):
        distance_sq = (x_m - source_x) ** 2 + (y_m - source_y) ** 2 + (0.57 - 0.8) ** 2
        value = background + strength / max(distance_sq, 0.25**2)
        service.add_sample(sample(index, x_m, y_m, value, index * 1_000_000_000))
    prediction = service.predict(len(positions) * 1_000_000_000)
    assert prediction.source_estimate is not None
    assert prediction.metrics["reconstruction_mode"] == "physical_global"
    assert prediction.source_estimate["x_m"] == pytest.approx(source_x, abs=0.4)
    assert prediction.source_estimate["y_m"] == pytest.approx(source_y, abs=0.4)
    correction_fraction = scenario.residual.maximum_relative_correction
    assert all(
        (1.0 - correction_fraction) * cell.posterior_mean - 1e-9
        <= cell.mean_uSv_h
        <= (1.0 + correction_fraction) * cell.posterior_mean + 1e-9
        for cell in prediction.adaptive_cells
    )
    assert any(
        value is not None and not covered
        for value, covered in zip(
            prediction.values_row_major,
            prediction.coverage_mask_row_major,
            strict=True,
        )
    )
    repeated = service.predict(len(positions) * 1_000_000_000 + 500_000_000)
    assert repeated.values_row_major == prediction.values_row_major
