"""Validate the V0.4.6 regulatory scale and preserve the video regression."""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

from validate_v045 import validate_10_sv_h_range, validate_video_path

from ares_mapper.config import (
    IOE_INVESTIGATION_EQUIVALENT_RATE_USV_H,
    IOE_LIMIT_EQUIVALENT_RATE_USV_H,
    IOE_MAXIMUM_EQUIVALENT_RATE_USV_H,
    IOE_RECORDING_EQUIVALENT_RATE_USV_H,
    IOE_REFERENCE_HOURS_PER_YEAR,
    PUBLIC_CONTINUOUS_REFERENCE_RATE_USV_H,
    load_scenario,
)
from ares_mapper.radiological_scale import (
    PUBLIC_REFERENCE_FRACTION,
    regulatory_scale_anchors,
    regulatory_scale_fraction,
)


def main() -> None:
    started = time.perf_counter()
    video_path = validate_video_path()
    high_range = validate_10_sv_h_range()
    scenario = load_scenario("config/scenarios/static_source.yaml")
    anchors = regulatory_scale_anchors()
    labelled = {
        anchor.rate_uSv_h: {
            "label": anchor.label,
            "fraction": anchor.fraction,
            "rgb": list(anchor.rgb),
        }
        for anchor in anchors
        if anchor.label
    }
    expected_rates = {
        "public_limit": PUBLIC_CONTINUOUS_REFERENCE_RATE_USV_H,
        "ioe_recording": IOE_RECORDING_EQUIVALENT_RATE_USV_H,
        "ioe_investigation": IOE_INVESTIGATION_EQUIVALENT_RATE_USV_H,
        "ioe_limit": IOE_LIMIT_EQUIVALENT_RATE_USV_H,
        "ioe_maximum_single_year": IOE_MAXIMUM_EQUIVALENT_RATE_USV_H,
    }
    ordered_rates = list(expected_rates.values())
    ordered_fractions = [
        regulatory_scale_fraction(rate) for rate in ordered_rates
    ]
    acceptance = {
        "source_error_below_0_25_m": video_path["source_position_error_m"] < 0.25,
        "no_remote_peaks": video_path["remote_peak_count"] == 0,
        "transition_completed": (
            video_path["final_reconstruction_mode"] == "physical_global"
            and video_path["final_global_blend"] == 1.0
        ),
        "no_abrupt_return_to_local": not video_path["returned_abruptly_to_local"],
        "near_source_color_change_below_0_10": (
            video_path["maximum_near_source_color_change_fraction"] < 0.10
        ),
        "map_deterministic_without_measurement": video_path[
            "map_unchanged_without_measurement"
        ],
        "render_p95_below_250_ms": video_path["render_latency_p95_ms"] < 250.0,
        "10_sv_h_pipeline_is_finite": high_range["all_detector_outputs_finite"],
        "public_reference_is_green": math.isclose(
            regulatory_scale_fraction(PUBLIC_CONTINUOUS_REFERENCE_RATE_USV_H),
            PUBLIC_REFERENCE_FRACTION,
        ),
        "ioe_uses_2000_hours_per_year": IOE_REFERENCE_HOURS_PER_YEAR == 2_000.0,
        "annualized_rates_are_exact": expected_rates == {
            "public_limit": 1_000.0 / 8_760.0,
            "ioe_recording": 0.5,
            "ioe_investigation": 3.0,
            "ioe_limit": 10.0,
            "ioe_maximum_single_year": 25.0,
        },
        "regulatory_levels_get_progressively_hotter": (
            ordered_fractions == sorted(ordered_fractions)
            and labelled[25.0]["rgb"] == [220, 47, 54]
        ),
        "scenario_uses_regulatory_scale": (
            scenario.dashboard.scale_mode == "regulatory_reference"
            and scenario.dashboard.subtract_background_for_scale
        ),
    }
    report = {
        "software_version": "0.4.6",
        "validation_type": "regulatory_scale_and_video_regression",
        "regulatory_scale": {
            "annualization": {
                "public_hours_per_year": 8_760.0,
                "ioe_hours_per_year": IOE_REFERENCE_HOURS_PER_YEAR,
            },
            "equivalent_rates_uSv_h": expected_rates,
            "labelled_anchors": labelled,
            "background_subtracted": (
                scenario.dashboard.subtract_background_for_scale
            ),
        },
        "video_path": video_path,
        "high_range": high_range,
        "acceptance": acceptance,
        "all_acceptance_checks_passed": all(acceptance.values()),
        "elapsed_s": time.perf_counter() - started,
    }
    output = Path("validation/v0.4.6_acceptance.json")
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["all_acceptance_checks_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
