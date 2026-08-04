import numpy as np
import pytest

from ares_mapper.config import load_scenario
from ares_mapper.simulation.detector import DetectorModel
from ares_mapper.simulation.radiation_field import RadiationField


def test_inverse_square_decreases_with_distance() -> None:
    scenario = load_scenario("config/scenarios/static_source.yaml")
    field = RadiationField(scenario.world, scenario.radiation_sources)
    source = scenario.radiation_sources[0]
    sx, sy, sz = field.source_position(source, 0)
    near = field.dose_rate(sx + 1, sy, sz, 0)
    far = field.dose_rate(sx + 2, sy, sz, 0)
    background = scenario.world.background.dose_rate_uSv_h
    assert near - background == pytest.approx(4 * (far - background))


def test_detector_is_deterministic_and_non_negative() -> None:
    scenario = load_scenario("config/scenarios/static_source.yaml")
    config = scenario.detectors[0]
    first = DetectorModel(config, np.random.Generator(np.random.PCG64(42)))
    second = DetectorModel(config, np.random.Generator(np.random.PCG64(42)))
    first_values = [first.measure(0.5, 1.0) for _ in range(10)]
    second_values = [second.measure(0.5, 1.0) for _ in range(10)]
    assert first_values == second_values
    assert all(item.dose_rate_uSv_h >= 0 for item in first_values)


def test_manual_simulation_does_not_turn_low_rates_into_zero_count_spikes() -> None:
    scenario = load_scenario("config/scenarios/static_source.yaml")
    config = scenario.detectors[0].model_copy(
        update={
            "additive_noise_std_uSv_h": 0.0,
            "multiplicative_noise_fraction": 0.0,
            "dose_rate_quantization_uSv_h": 0.0,
        }
    )
    assert config.response_mode == "dose_direct"
    model = DetectorModel(config, np.random.Generator(np.random.PCG64(42)))
    reading = model.measure(0.246, 1.0)
    assert reading.dose_rate_uSv_h == pytest.approx(0.246)


def test_moving_source_keyframes_change_position() -> None:
    scenario = load_scenario("config/scenarios/moving_source.yaml")
    field = RadiationField(scenario.world, scenario.radiation_sources)
    source = scenario.radiation_sources[0]
    assert field.source_position(source, 59) == pytest.approx((7.5, 5.5, 0.8))
    assert field.source_position(source, 65) == pytest.approx((3.0, 2.5, 0.8))


def test_live_source_update_is_a_step_without_rewriting_the_past() -> None:
    scenario = load_scenario("config/scenarios/static_source.yaml")
    field = RadiationField(scenario.world, scenario.radiation_sources)
    source = scenario.radiation_sources[0]
    original_position = field.source_position(source, 4.9)
    original_strength = field.source_strength(source, 4.9)

    field.update_source(source.id, 5.0, x_m=3.0, y_m=4.0, strength_uSv_h=6.0)

    assert field.source_position(source, 4.9) == original_position
    assert field.source_strength(source, 4.9) == original_strength
    assert field.source_position(source, 5.0) == pytest.approx((3.0, 4.0, 0.8))
    assert field.source_strength(source, 5.0) == pytest.approx(6.0)
