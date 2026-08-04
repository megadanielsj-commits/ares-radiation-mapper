"""Validate the V0.4.8 Unitree Go2 footprint and stable dashboard avatar."""

from __future__ import annotations

import json
import time
from pathlib import Path

from ares_mapper.config import (
    UNITREE_GO2_STANDING_HEIGHT_M,
    UNITREE_GO2_STANDING_LENGTH_M,
    UNITREE_GO2_STANDING_WIDTH_M,
    load_scenario,
)
from ares_mapper.version import __version__


def main() -> None:
    started = time.perf_counter()
    scenario = load_scenario("config/scenarios/static_source.yaml")
    real_go2 = load_scenario("config/hardware/go2_fs5000.yaml")
    interface_script = Path("src/ares_mapper/web/static/app.js").read_text(encoding="utf-8")

    geometry = scenario.robot
    wide_map_scale_px_per_m = 600.0 / 50.0
    physical_length_px_on_wide_map = geometry.length_m * wide_map_scale_px_per_m
    displayed_length_px_on_wide_map = max(
        physical_length_px_on_wide_map,
        geometry.minimum_display_length_px,
    )
    acceptance = {
        "official_standing_dimensions_are_encoded": (
            UNITREE_GO2_STANDING_LENGTH_M == 0.70
            and UNITREE_GO2_STANDING_WIDTH_M == 0.31
            and UNITREE_GO2_STANDING_HEIGHT_M == 0.40
        ),
        "scenario_uses_official_dimensions": (
            geometry.length_m == UNITREE_GO2_STANDING_LENGTH_M
            and geometry.width_m == UNITREE_GO2_STANDING_WIDTH_M
            and geometry.height_m == UNITREE_GO2_STANDING_HEIGHT_M
        ),
        "real_go2_profile_uses_same_geometry": (
            real_go2.robot.length_m == geometry.length_m
            and real_go2.robot.width_m == geometry.width_m
            and real_go2.robot.height_m == geometry.height_m
        ),
        "wide_map_avatar_has_legible_minimum": (
            physical_length_px_on_wide_map < 10.0 and displayed_length_px_on_wide_map >= 30.0
        ),
        "canvas_preserves_physical_footprint": (
            "physicalLengthPx = geometry.lengthM * plot.scale" in interface_script
            and "physicalWidthPx = geometry.widthM * plot.scale" in interface_script
            and "physicalPoints" in interface_script
        ),
        "canvas_has_minimum_legible_avatar": (
            "geometry.minimumDisplayLengthPx" in interface_script
            and "Math.max(" in interface_script
        ),
        "yaw_aware_visual_smoothing_is_present": (
            "function shortestAngleDelta" in interface_script
            and "visual_smoothing_time_constant_s" in interface_script
            and "displayPoseNeedsAnimation" in interface_script
        ),
    }
    report = {
        "software_version": __version__,
        "validation_type": "unitree_go2_avatar_and_real_hardware_profile",
        "go2_standing_dimensions_m": {
            "length": geometry.length_m,
            "width": geometry.width_m,
            "height": geometry.height_m,
        },
        "wide_map_example": {
            "span_m": 50.0,
            "plot_width_px": 600.0,
            "physical_length_px": physical_length_px_on_wide_map,
            "displayed_length_px": displayed_length_px_on_wide_map,
        },
        "acceptance": acceptance,
        "all_acceptance_checks_passed": all(acceptance.values()),
        "elapsed_s": time.perf_counter() - started,
    }
    output = Path("validation/v0.4.8_acceptance.json")
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["all_acceptance_checks_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
