"""Validate the V0.4.7 classic palette and preserve the V0.4.6 pipeline."""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

from validate_v045 import validate_10_sv_h_range, validate_video_path

from ares_mapper.config import (
    DEFAULT_SIMULATION_SOURCE_STRENGTH_USV_H,
    IOE_INVESTIGATION_EQUIVALENT_RATE_USV_H,
    IOE_LIMIT_EQUIVALENT_RATE_USV_H,
    IOE_MAXIMUM_EQUIVALENT_RATE_USV_H,
    IOE_RECORDING_EQUIVALENT_RATE_USV_H,
    MAX_SIMULATION_SOURCE_STRENGTH_USV_H,
    PUBLIC_CONTINUOUS_REFERENCE_RATE_USV_H,
    load_scenario,
)
from ares_mapper.radiological_scale import (
    ARES_CLASSIC_COLOR_STOPS,
    classic_scale_anchors,
    logarithmic_scale_fraction,
    mission_scale_bounds,
)
from ares_mapper.version import __version__


def main() -> None:
    started = time.perf_counter()
    video_path = validate_video_path()
    high_range = validate_10_sv_h_range()
    scenario = load_scenario("config/scenarios/static_source.yaml")
    source_rate = (
        scenario.radiation_sources[0]
        .strength_keyframes[0]
        .dose_rate_at_reference_uSv_h
    )
    expected_minimum, expected_maximum = mission_scale_bounds(
        source_rate,
        background_rate_uSv_h=(
            scenario.world.background.dose_rate_uSv_h
        ),
        physical_minimum_distance_m=(
            scenario.mapping.source_minimum_distance_m
        ),
    )
    anchors = classic_scale_anchors(
        minimum_rate_uSv_h=expected_minimum,
        maximum_rate_uSv_h=expected_maximum,
    )
    interface_script = Path(
        "src/ares_mapper/web/static/app.js"
    ).read_text(encoding="utf-8")
    reference_rates = {
        "public_limit": PUBLIC_CONTINUOUS_REFERENCE_RATE_USV_H,
        "ioe_recording": IOE_RECORDING_EQUIVALENT_RATE_USV_H,
        "ioe_investigation": IOE_INVESTIGATION_EQUIVALENT_RATE_USV_H,
        "ioe_limit": IOE_LIMIT_EQUIVALENT_RATE_USV_H,
        "ioe_maximum_single_year": IOE_MAXIMUM_EQUIVALENT_RATE_USV_H,
    }
    acceptance = {
        "source_error_below_0_25_m": video_path["source_position_error_m"] < 0.25,
        "no_remote_peaks": video_path["remote_peak_count"] == 0,
        "transition_completed": (
            video_path["final_reconstruction_mode"] == "physical_global"
            and video_path["final_global_blend"] == 1.0
        ),
        "map_deterministic_without_measurement": video_path[
            "map_unchanged_without_measurement"
        ],
        "render_p95_below_250_ms": video_path["render_latency_p95_ms"] < 250.0,
        "10_sv_h_pipeline_is_finite": high_range["all_detector_outputs_finite"],
        "default_source_is_10_msv_h": (
            source_rate == DEFAULT_SIMULATION_SOURCE_STRENGTH_USV_H
        ),
        "maximum_source_is_10_sv_h": (
            MAX_SIMULATION_SOURCE_STRENGTH_USV_H == 10_000_000.0
        ),
        "scenario_uses_classic_log_scale": (
            scenario.dashboard.color_scale == "AresClassic"
            and scenario.dashboard.scale_mode == "log_fixed"
            and not scenario.dashboard.subtract_background_for_scale
        ),
        "scenario_bounds_match_source": (
            math.isclose(
                scenario.dashboard.scale_min_uSv_h,
                expected_minimum,
            )
            and math.isclose(
                scenario.dashboard.scale_max_uSv_h,
                expected_maximum,
            )
        ),
        "classic_palette_has_six_original_stops": (
            [(anchor.fraction, anchor.rgb) for anchor in anchors]
            == list(ARES_CLASSIC_COLOR_STOPS)
        ),
        "classic_palette_is_present_in_canvas": all(
            str(list(rgb)) in interface_script
            for _, rgb in ARES_CLASSIC_COLOR_STOPS
        ),
        "minimum_and_maximum_span_full_palette": (
            math.isclose(
                logarithmic_scale_fraction(
                    expected_minimum,
                    minimum_rate_uSv_h=expected_minimum,
                    maximum_rate_uSv_h=expected_maximum,
                ),
                0.0,
            )
            and math.isclose(
                logarithmic_scale_fraction(
                    expected_maximum,
                    minimum_rate_uSv_h=expected_minimum,
                    maximum_rate_uSv_h=expected_maximum,
                ),
                1.0,
            )
        ),
        "regulatory_references_are_preserved": reference_rates == {
            "public_limit": 1_000.0 / 8_760.0,
            "ioe_recording": 0.5,
            "ioe_investigation": 3.0,
            "ioe_limit": 10.0,
            "ioe_maximum_single_year": 25.0,
        },
    }
    report = {
        "software_version": __version__,
        "validation_type": "classic_palette_and_video_regression",
        "display_scale": {
            "mode": scenario.dashboard.scale_mode,
            "palette": [
                {
                    "fraction": fraction,
                    "rgb": list(rgb),
                }
                for fraction, rgb in ARES_CLASSIC_COLOR_STOPS
            ],
            "minimum_uSv_h": expected_minimum,
            "maximum_uSv_h": expected_maximum,
            "regulatory_references_control_colours": False,
        },
        "regulatory_reference_rates_uSv_h": reference_rates,
        "video_path": video_path,
        "high_range": high_range,
        "acceptance": acceptance,
        "all_acceptance_checks_passed": all(acceptance.values()),
        "elapsed_s": time.perf_counter() - started,
    }
    output = Path("validation/v0.4.7_acceptance.json")
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["all_acceptance_checks_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
