from pathlib import Path

import pytest
from pydantic import ValidationError

from ares_mapper.config import (
    DEFAULT_SIMULATION_SOURCE_STRENGTH_USV_H,
    HOURS_PER_REFERENCE_YEAR,
    IOE_ANNUAL_EFFECTIVE_DOSE_LIMIT_MSV,
    IOE_ANNUAL_INVESTIGATION_LEVEL_MSV,
    IOE_ANNUAL_RECORDING_LEVEL_MSV,
    IOE_INVESTIGATION_EQUIVALENT_RATE_USV_H,
    IOE_LIMIT_EQUIVALENT_RATE_USV_H,
    IOE_MAXIMUM_EQUIVALENT_RATE_USV_H,
    IOE_MAXIMUM_SINGLE_YEAR_EFFECTIVE_DOSE_MSV,
    IOE_RECORDING_EQUIVALENT_RATE_USV_H,
    IOE_REFERENCE_HOURS_PER_YEAR,
    MAX_SIMULATION_SOURCE_STRENGTH_USV_H,
    PUBLIC_ANNUAL_EFFECTIVE_DOSE_LIMIT_MSV,
    PUBLIC_CONTINUOUS_REFERENCE_RATE_USV_H,
    UNITREE_GO2_CROUCHED_HEIGHT_M,
    UNITREE_GO2_CROUCHED_LENGTH_M,
    UNITREE_GO2_CROUCHED_WIDTH_M,
    UNITREE_GO2_STANDING_HEIGHT_M,
    UNITREE_GO2_STANDING_LENGTH_M,
    UNITREE_GO2_STANDING_WIDTH_M,
    ScenarioConfig,
    load_scenario,
)
from ares_mapper.radiological_scale import (
    ARES_CLASSIC_COLOR_STOPS,
    PUBLIC_REFERENCE_FRACTION,
    classic_scale_anchors,
    logarithmic_scale_fraction,
    mission_scale_bounds,
    regulatory_scale_anchors,
    regulatory_scale_fraction,
)


def test_all_bundled_scenarios_are_valid() -> None:
    paths = sorted(Path("config/scenarios").glob("*.yaml"))
    assert len(paths) >= 6
    for path in paths:
        scenario = load_scenario(path)
        assert scenario.schema_version in {"1.0", "1.1"}
        assert scenario.mission.mode in {"sim", "simulated"}


def test_configuration_hash_is_stable() -> None:
    first = load_scenario("config/scenarios/static_source.yaml")
    second = load_scenario("config/scenarios/static_source.yaml")
    assert first.configuration_hash() == second.configuration_hash()


def test_go2_geometry_is_consistent() -> None:
    assert UNITREE_GO2_STANDING_LENGTH_M == 0.70
    assert UNITREE_GO2_STANDING_WIDTH_M == 0.31
    assert UNITREE_GO2_STANDING_HEIGHT_M == 0.40
    assert UNITREE_GO2_CROUCHED_LENGTH_M == 0.76
    assert UNITREE_GO2_CROUCHED_WIDTH_M == 0.31
    assert UNITREE_GO2_CROUCHED_HEIGHT_M == 0.20

    scenario = load_scenario("config/scenarios/static_source.yaml")
    assert scenario.robot.model == "unitree_go2"
    assert scenario.robot.posture == "standing"
    assert scenario.robot.length_m == UNITREE_GO2_STANDING_LENGTH_M
    assert scenario.robot.width_m == UNITREE_GO2_STANDING_WIDTH_M
    assert scenario.robot.height_m == UNITREE_GO2_STANDING_HEIGHT_M
    assert scenario.robot.minimum_display_length_px == 30.0
    assert scenario.robot.visual_smoothing_time_constant_s == 0.08


def test_public_reference_and_default_source_scale_are_consistent() -> None:
    expected = PUBLIC_ANNUAL_EFFECTIVE_DOSE_LIMIT_MSV * 1_000 / HOURS_PER_REFERENCE_YEAR
    assert pytest.approx(expected) == PUBLIC_CONTINUOUS_REFERENCE_RATE_USV_H
    assert pytest.approx(0.1141552511415525) == PUBLIC_CONTINUOUS_REFERENCE_RATE_USV_H
    assert DEFAULT_SIMULATION_SOURCE_STRENGTH_USV_H == 10_000.0
    assert MAX_SIMULATION_SOURCE_STRENGTH_USV_H == 10_000_000.0

    scenario = load_scenario("config/scenarios/static_source.yaml")
    source_rate = scenario.radiation_sources[0].strength_keyframes[0].dose_rate_at_reference_uSv_h
    assert source_rate == DEFAULT_SIMULATION_SOURCE_STRENGTH_USV_H
    assert scenario.dashboard.color_scale == "AresClassic"
    assert scenario.dashboard.scale_mode == "log_fixed"
    assert scenario.dashboard.scale_min_uSv_h == pytest.approx(0.1)
    assert scenario.dashboard.scale_max_uSv_h == pytest.approx(40_000.1)
    assert scenario.dashboard.subtract_background_for_scale is False


def test_classic_palette_uses_mission_relative_logarithmic_bounds() -> None:
    minimum, maximum = mission_scale_bounds(
        10_000.0,
        background_rate_uSv_h=0.1,
        physical_minimum_distance_m=0.25,
    )
    assert minimum == pytest.approx(0.1)
    assert maximum == pytest.approx(40_000.1)
    assert logarithmic_scale_fraction(
        minimum,
        minimum_rate_uSv_h=minimum,
        maximum_rate_uSv_h=maximum,
    ) == pytest.approx(0.0)
    assert logarithmic_scale_fraction(
        maximum,
        minimum_rate_uSv_h=minimum,
        maximum_rate_uSv_h=maximum,
    ) == pytest.approx(1.0)
    anchors = classic_scale_anchors(
        minimum_rate_uSv_h=minimum,
        maximum_rate_uSv_h=maximum,
    )
    assert [(anchor.fraction, anchor.rgb) for anchor in anchors] == list(ARES_CLASSIC_COLOR_STOPS)


def test_regulatory_reference_levels_are_preserved_for_annotations() -> None:
    reference = PUBLIC_CONTINUOUS_REFERENCE_RATE_USV_H
    assert IOE_REFERENCE_HOURS_PER_YEAR == 2_000.0
    assert IOE_ANNUAL_RECORDING_LEVEL_MSV == 1.0
    assert IOE_ANNUAL_INVESTIGATION_LEVEL_MSV == 6.0
    assert IOE_ANNUAL_EFFECTIVE_DOSE_LIMIT_MSV == 20.0
    assert IOE_MAXIMUM_SINGLE_YEAR_EFFECTIVE_DOSE_MSV == 50.0
    assert IOE_RECORDING_EQUIVALENT_RATE_USV_H == 0.5
    assert IOE_INVESTIGATION_EQUIVALENT_RATE_USV_H == 3.0
    assert IOE_LIMIT_EQUIVALENT_RATE_USV_H == 10.0
    assert IOE_MAXIMUM_EQUIVALENT_RATE_USV_H == 25.0

    assert regulatory_scale_fraction(0.0) == 0.0
    assert regulatory_scale_fraction(reference) == pytest.approx(PUBLIC_REFERENCE_FRACTION)
    assert regulatory_scale_fraction(MAX_SIMULATION_SOURCE_STRENGTH_USV_H) == 1.0
    values = [
        regulatory_scale_fraction(rate)
        for rate in [
            0.0,
            reference,
            0.5,
            3.0,
            10.0,
            25.0,
            1_000.0,
            100_000.0,
            10_000_000.0,
        ]
    ]
    assert values == sorted(values)
    anchors = regulatory_scale_anchors()
    green = next(
        anchor for anchor in anchors if anchor.rate_uSv_h == PUBLIC_CONTINUOUS_REFERENCE_RATE_USV_H
    )
    assert green.rgb == (43, 183, 94)
    labelled = {anchor.rate_uSv_h: (anchor.label, anchor.rgb) for anchor in anchors if anchor.label}
    assert labelled[0.5][0] == "IOE registro · 1 mSv/ano"
    assert labelled[3.0][0] == "IOE investigação · 6 mSv/ano"
    assert labelled[10.0][0] == "IOE limite · 20 mSv/ano"
    assert labelled[25.0][0] == "IOE teto · 50 mSv/ano"
    assert labelled[25.0][1] == (220, 47, 54)


def test_duplicate_detector_ids_are_rejected() -> None:
    scenario = load_scenario("config/scenarios/static_source.yaml")
    raw = scenario.model_dump(mode="json")
    raw["detectors"].append(raw["detectors"][0].copy())
    with pytest.raises(ValidationError):
        ScenarioConfig.model_validate(raw)
