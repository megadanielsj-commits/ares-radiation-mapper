"""Reproduce the video path and V0.4.5 radiological-scale checks."""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import numpy as np

from ares_mapper.config import (
    DEFAULT_SIMULATION_SOURCE_STRENGTH_USV_H,
    MAX_SIMULATION_SOURCE_STRENGTH_USV_H,
    PUBLIC_CONTINUOUS_REFERENCE_RATE_USV_H,
    load_scenario,
)
from ares_mapper.core.mission_controller import MissionController
from ares_mapper.core.synchronizer import TemporalSynchronizer
from ares_mapper.core.transforms import yaw_to_quaternion
from ares_mapper.domain.models import PoseSample, RadiationSample
from ares_mapper.mapping.service import MapService
from ares_mapper.radiological_scale import (
    PUBLIC_REFERENCE_FRACTION,
    public_scale_fraction,
)
from ares_mapper.simulation.detector import DetectorModel

SOURCE_X_M = 7.0
SOURCE_Y_M = 5.0
SOURCE_RATE_USV_H = 100_000.0
WAYPOINTS = [
    (0.0, 2.0, 2.0),
    (3.0, 2.0, 2.0),
    (15.2, 7.0, 1.0),
    (24.1, 7.0, 5.0),
    (29.1, 7.0, 5.0),
    (33.55, 7.0, 7.0),
    (39.85, 9.0, 5.0),
    (48.75, 5.0, 5.0),
    (52.0, 5.0, 5.0),
]


def state_at(time_s: float) -> tuple[float, float, float, float]:
    for (start_s, x0, y0), (end_s, x1, y1) in zip(
        WAYPOINTS,
        WAYPOINTS[1:],
        strict=False,
    ):
        if time_s <= end_s + 1e-12:
            duration_s = max(end_s - start_s, 1e-9)
            fraction = min(1.0, max(0.0, (time_s - start_s) / duration_s))
            return (
                x0 + fraction * (x1 - x0),
                y0 + fraction * (y1 - y0),
                (x1 - x0) / duration_s,
                (y1 - y0) / duration_s,
            )
    return WAYPOINTS[-1][1], WAYPOINTS[-1][2], 0.0, 0.0


def add_pose_history(
    synchronizer: TemporalSynchronizer,
    mission_id: str,
    time_domain_id: str,
) -> None:
    qx, qy, qz, qw = yaw_to_quaternion(0.0)
    for sequence, tick in enumerate(
        range(int(WAYPOINTS[-1][0] * 20) + 1),
        start=1,
    ):
        time_s = tick / 20.0
        x_m, y_m, vx_m_s, vy_m_s = state_at(time_s)
        time_ns = int(round(time_s * 1_000_000_000))
        synchronizer.add_pose(
            PoseSample(
                mission_id=mission_id,
                source_id="manual_pose",
                sequence=sequence,
                time_domain_id=time_domain_id,
                timeline_time_ns=time_ns,
                source_time_ns=time_ns,
                received_utc_ns=0,
                received_monotonic_ns=time_ns,
                frame_id="world",
                child_frame_id="base",
                x_m=x_m,
                y_m=y_m,
                z_m=0.32,
                qx=qx,
                qy=qy,
                qz=qz,
                qw=qw,
                yaw_rad=0.0,
                vx_m_s=vx_m_s,
                vy_m_s=vy_m_s,
                position_std_m=0.01,
            )
        )


def validate_video_path() -> dict[str, object]:
    scenario = load_scenario("config/scenarios/static_source.yaml")
    controller = MissionController(scenario)
    controller.configure_static_simulation_source(
        x_m=SOURCE_X_M,
        y_m=SOURCE_Y_M,
        dose_rate_at_1m_uSv_h=SOURCE_RATE_USV_H,
    )
    scenario = controller.scenario
    field = controller.field
    assert field is not None
    detector = scenario.detectors[0]
    mission_id = "v045-video-path"
    time_domain_id = f"sim:{mission_id}"
    synchronizer = TemporalSynchronizer(
        scenario.synchronization,
        {detector.sensor_id: detector.transform_base_sensor},
        buffer_duration_s=120.0,
        detectors={detector.sensor_id: detector},
    )
    add_pose_history(synchronizer, mission_id, time_domain_id)
    service = MapService(
        mission_id,
        scenario.world,
        scenario.mapping,
        field,
        inference=scenario.inference,
        grid_config=scenario.grid,
        residual_config=scenario.residual,
        detectors=scenario.detectors,
        seed=scenario.mission.seed,
    )
    detector_model = DetectorModel(
        detector,
        np.random.Generator(np.random.PCG64(20260729)),
    )

    transition_observation: int | None = None
    full_observation: int | None = None
    peak_locations: list[tuple[int, float, float]] = []
    full_global_peak_locations: list[tuple[int, float, float]] = []
    blend_sequence: list[tuple[int, float]] = []
    all_blends: list[float] = []
    color_changes: list[float] = []
    render_latencies_ms: list[float] = []
    response_delays_s: list[float] = []
    previous_near_source: np.ndarray | None = None
    final_prediction = None
    background_rate = scenario.world.background.dose_rate_uSv_h

    for sequence in range(1, 53):
        start_s = sequence - 1.0
        end_s = float(sequence)
        sample_times_s = np.linspace(start_s, end_s, 11)
        truth_rates = []
        for sample_time_s in sample_times_s:
            x_m, y_m, _, _ = state_at(float(sample_time_s))
            truth_rates.append(
                field.dose_rate(x_m, y_m, 0.57, float(sample_time_s))
            )
        reading = detector_model.measure(float(np.mean(truth_rates)), 1.0)
        radiation = RadiationSample(
            mission_id=mission_id,
            sensor_id=detector.sensor_id,
            sequence=sequence,
            time_domain_id=time_domain_id,
            timeline_time_ns=int(end_s * 1_000_000_000),
            source_time_ns=int(end_s * 1_000_000_000),
            received_utc_ns=0,
            received_monotonic_ns=int(end_s * 1_000_000_000),
            effective_measurement_time_ns=int((start_s + 0.5) * 1_000_000_000),
            dose_rate_uSv_h=reading.dose_rate_uSv_h,
            cumulative_dose_uSv=reading.cumulative_dose_uSv,
            cps=reading.cps,
            cpm=reading.cpm,
            average_dose_rate_uSv_h=reading.average_dose_rate_uSv_h,
            integration_time_s=1.0,
            integration_start_time_ns=int(start_s * 1_000_000_000),
            integration_end_time_ns=int(end_s * 1_000_000_000),
            quality=reading.quality,
        )
        window = synchronizer.build_observation_window(
            radiation,
            detector.observation_mode,
        )
        assert window is not None
        response_delays_s.append(window.response_delay_s)
        mapped = synchronizer.mapped_from_window(window, radiation)
        service.add_observation(window, mapped)
        prediction = service.predict(int(end_s * 1_000_000_000))
        final_prediction = prediction
        mode = str(prediction.metrics["reconstruction_mode"])
        blend = float(prediction.metrics.get("global_model_blend", 0.0))
        all_blends.append(blend)
        if blend > 0:
            blend_sequence.append((sequence, blend))
        if mode == "physical_transition" and transition_observation is None:
            transition_observation = sequence
        if mode == "physical_global" and full_observation is None:
            full_observation = sequence
        render_latencies_ms.append(float(prediction.metrics["render_latency_ms"]))

        values = np.asarray(
            [
                np.nan if value is None else float(value)
                for value in prediction.values_row_major
            ]
        ).reshape(prediction.grid_shape)
        if np.any(np.isfinite(values)):
            row, column = np.unravel_index(int(np.nanargmax(values)), values.shape)
            peak_locations.append(
                (
                    sequence,
                    float(prediction.x_coordinates_m[column]),
                    float(prediction.y_coordinates_m[row]),
                )
            )
            if mode == "physical_global":
                full_global_peak_locations.append(peak_locations[-1])
        x_grid = np.asarray(prediction.x_coordinates_m)
        y_grid = np.asarray(prediction.y_coordinates_m)
        near_source = (
            (x_grid[None, :] - SOURCE_X_M) ** 2
            + (y_grid[:, None] - SOURCE_Y_M) ** 2
            <= 1.0
        )
        current_near_source = values[near_source]
        if (
            previous_near_source is not None
            and np.all(np.isfinite(previous_near_source))
            and np.all(np.isfinite(current_near_source))
        ):
            previous_color = np.asarray(
                [
                    public_scale_fraction(max(value - background_rate, 0.0))
                    for value in previous_near_source
                ]
            )
            current_color = np.asarray(
                [
                    public_scale_fraction(max(value - background_rate, 0.0))
                    for value in current_near_source
                ]
            )
            color_changes.append(
                float(np.percentile(np.abs(current_color - previous_color), 95))
            )
        previous_near_source = current_near_source.copy()

    assert final_prediction is not None
    posterior = final_prediction.source_posterior
    assert posterior is not None
    display_parameters = service.reconstructor._display_parameters  # noqa: SLF001
    assert display_parameters is not None
    source_error_m = math.hypot(
        posterior.posterior_map_x_y[0] - SOURCE_X_M,
        posterior.posterior_map_x_y[1] - SOURCE_Y_M,
    )
    remote_peaks = [
        item
        for item in full_global_peak_locations
        if math.hypot(item[1] - SOURCE_X_M, item[2] - SOURCE_Y_M) > 0.75
    ]
    repeated = service.predict(final_prediction.map_time_ns + 500_000_000)
    map_is_deterministic = repeated.values_row_major == final_prediction.values_row_major
    first_global_index = next(
        (index for index, blend in enumerate(all_blends) if blend > 0),
        None,
    )
    returned_to_local = (
        first_global_index is not None
        and any(blend == 0.0 for blend in all_blends[first_global_index + 1 :])
    )

    def value_at(x_m: float, y_m: float) -> float | None:
        column = int(np.argmin(np.abs(np.asarray(final_prediction.x_coordinates_m) - x_m)))
        row = int(np.argmin(np.abs(np.asarray(final_prediction.y_coordinates_m) - y_m)))
        value = final_prediction.values_row_major[
            row * len(final_prediction.x_coordinates_m) + column
        ]
        return None if value is None else float(value)

    return {
        "source_truth": {
            "x_m": SOURCE_X_M,
            "y_m": SOURCE_Y_M,
            "dose_rate_at_1m_uSv_h": SOURCE_RATE_USV_H,
        },
        "observations": 52,
        "first_transition_observation": transition_observation,
        "first_full_global_observation": full_observation,
        "final_reconstruction_mode": final_prediction.metrics["reconstruction_mode"],
        "final_global_blend": final_prediction.metrics["global_model_blend"],
        "source_position_error_m": source_error_m,
        "posterior_map_x_y": posterior.posterior_map_x_y,
        "display_source_x_y": [
            float(display_parameters[0]),
            float(display_parameters[1]),
        ],
        "estimated_strength_at_1m_uSv_h": posterior.posterior_median_strength_at_1m,
        "remote_peak_count": len(remote_peaks),
        "remote_peak_locations": remote_peaks,
        "diagnostic_values_uSv_h": {
            "at_6_5": value_at(6.0, 5.0),
            "at_6_75_5": value_at(6.75, 5.0),
            "at_7_5": value_at(7.0, 5.0),
        },
        "maximum_near_source_color_change_fraction": max(color_changes, default=0.0),
        "steady_response_delay_s": response_delays_s[-1],
        "render_latency_p95_ms": float(np.percentile(render_latencies_ms, 95)),
        "map_unchanged_without_measurement": map_is_deterministic,
        "returned_abruptly_to_local": returned_to_local,
    }


def validate_10_sv_h_range() -> dict[str, object]:
    scenario = load_scenario("config/scenarios/static_source.yaml")
    controller = MissionController(scenario)
    configured = controller.configure_static_simulation_source(
        x_m=4.0,
        y_m=4.0,
        dose_rate_at_1m_uSv_h=MAX_SIMULATION_SOURCE_STRENGTH_USV_H,
    )
    field = controller.field
    assert field is not None
    source = controller.scenario.radiation_sources[0]
    source_z_m = source.position_keyframes[0].z_m
    rate_at_1m = field.dose_rate(5.0, 4.0, source_z_m, 0.0)
    detector = controller.scenario.detectors[0]
    detector_model = DetectorModel(
        detector,
        np.random.Generator(np.random.PCG64(100)),
    )
    maximum_field_rate = field.dose_rate(4.0, 4.0, 0.57, 0.0)
    readings = [detector_model.measure(maximum_field_rate, 1.0) for _ in range(3)]
    return {
        "configured_rate_at_1m_uSv_h": configured["dose_rate_at_1m_uSv_h"],
        "field_rate_at_1m_uSv_h": rate_at_1m,
        "maximum_simulated_field_rate_uSv_h": maximum_field_rate,
        "all_detector_outputs_finite": all(
            math.isfinite(reading.dose_rate_uSv_h)
            and math.isfinite(reading.cumulative_dose_uSv)
            for reading in readings
        ),
        "inference_strength_range_uSv_h": [
            controller.scenario.inference.source_strength_min_uSv_h,
            controller.scenario.inference.source_strength_max_uSv_h,
        ],
    }


def main() -> None:
    started = time.perf_counter()
    video_path = validate_video_path()
    high_range = validate_10_sv_h_range()
    scenario = load_scenario("config/scenarios/static_source.yaml")
    configured_default = (
        scenario.radiation_sources[0]
        .strength_keyframes[0]
        .dose_rate_at_reference_uSv_h
    )
    acceptance = {
        "source_error_below_0_25_m": video_path["source_position_error_m"] < 0.25,
        "no_remote_peaks": video_path["remote_peak_count"] == 0,
        "transition_completed": (
            video_path["final_reconstruction_mode"] == "physical_global"
            and video_path["final_global_blend"] == 1.0
        ),
        "no_abrupt_return_to_local": not video_path["returned_abruptly_to_local"],
        "near_source_color_change_p95_below_0_10": (
            video_path["maximum_near_source_color_change_fraction"] < 0.10
        ),
        "map_deterministic_without_measurement": video_path[
            "map_unchanged_without_measurement"
        ],
        "render_p95_below_250_ms": video_path["render_latency_p95_ms"] < 250.0,
        "10_sv_h_pipeline_is_finite": high_range["all_detector_outputs_finite"],
        "default_source_is_10_msv_h": (
            configured_default == DEFAULT_SIMULATION_SOURCE_STRENGTH_USV_H
        ),
        "public_reference_is_1_msv_per_year_equivalent": math.isclose(
            PUBLIC_CONTINUOUS_REFERENCE_RATE_USV_H,
            1_000.0 / (365.0 * 24.0),
        ),
        "public_reference_is_green_anchor": math.isclose(
            public_scale_fraction(PUBLIC_CONTINUOUS_REFERENCE_RATE_USV_H),
            PUBLIC_REFERENCE_FRACTION,
        ),
    }
    report = {
        "software_version": "0.4.5",
        "validation_type": "video_regression_and_absolute_radiological_scale",
        "radiological_scale": {
            "default_source_uSv_h": configured_default,
            "maximum_source_uSv_h": MAX_SIMULATION_SOURCE_STRENGTH_USV_H,
            "public_continuous_reference_uSv_h": (
                PUBLIC_CONTINUOUS_REFERENCE_RATE_USV_H
            ),
            "public_reference_color_fraction": PUBLIC_REFERENCE_FRACTION,
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
    output = Path("validation/v0.4.5_acceptance.json")
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["all_acceptance_checks_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
