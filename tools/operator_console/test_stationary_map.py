"""Regression: dwell time must not erase the measured spatial trajectory."""
import math

import numpy as np
import pytest

from ares_mapper.domain.enums import MappingQuality, Quality, SyncMethod
from ares_mapper.domain.models import MappedSample
from ares_mapper.mapping.service import MapService
from tools.operator_console.runtime import Setup, scenario


@pytest.mark.parametrize("noise_fraction", [0.0, 0.02])
@pytest.mark.parametrize("dwell_position", [(7.5, 5.5), (7.66, 5.69)])
def test_stationary_source_preserves_field_and_records_every_reading(
    tmp_path, noise_fraction, dwell_position
):
    config = scenario(tmp_path, Setup())
    service = MapService("dwell", config.world, config.mapping,
                         inference=config.inference, grid_config=config.grid,
                         residual_config=config.residual, detectors=config.detectors,
                         seed=config.mission.seed)
    source = (7.5, 5.5)
    landmarks = [(2, 2), (1, 1), (9, 1), (9, 7), (1, 7), (1, 1), (9, 7),
                 (8, 6.5), (6, 6.5), (6, 4.5), (8, 4.5), (8, 6.5), source]
    positions = []
    for start, end in zip(landmarks, landmarks[1:]):
        count = max(1, math.ceil(math.dist(start, end) / .45))
        positions.extend((start[0] + (end[0] - start[0]) * t,
                          start[1] + (end[1] - start[1]) * t)
                         for t in np.linspace(0, 1, count, endpoint=False))
    positions.append(source)
    sequence = 0
    total_dose = 0.0
    rng = np.random.default_rng(123)

    def add(position):
        nonlocal sequence, total_dose
        sequence += 1
        x, y = position
        rate = (.1 + 10000 / max((x - source[0])**2 + (y - source[1])**2 + .23**2,
                                .25**2)) * (1 + rng.normal(0, noise_fraction))
        total_dose += rate / 3600
        service.add_sample(MappedSample(
            mission_id="dwell", mapped_sequence=sequence, radiation_sequence=sequence,
            sensor_id=config.detectors[0].sensor_id, time_domain_id="sim:dwell",
            effective_measurement_time_ns=sequence * 1_000_000_000, frame_id="world",
            base_x_m=x, base_y_m=y, base_z_m=.32, sensor_x_m=x, sensor_y_m=y,
            sensor_z_m=.57, sensor_yaw_rad=0, dose_rate_uSv_h_raw=rate,
            dose_rate_uSv_h_filtered=rate, integration_time_s=1,
            cumulative_dose_uSv=None, sync_method=SyncMethod.EXACT,
            max_pose_gap_ms=0, sync_error_estimate_ms=0, pose_quality=Quality.VALID,
            radiation_quality=Quality.VALID, mapping_quality=MappingQuality.VALID))

    for position in positions:
        add(position)
    before = service.predict(sequence * 1_000_000_000, include_truth=False)
    assert before.metrics["reconstruction_mode"] == "physical_global"
    before_median = np.nanmedian([np.nan if v is None else v for v in before.values_row_major])
    geometry_before = before.source_posterior.model_diagnostics

    # Longer than the original 512-position buffer; no movement between readings.
    for dwell in range(1, 551):
        add(dwell_position)
        if dwell in (20, 200, 550):
            after = service.predict(sequence * 1_000_000_000, include_truth=False)
            assert after.metrics["reconstruction_mode"] == "physical_global", (
                dwell, after.source_posterior.identifiability_state,
                after.source_posterior.posterior_mean_x_y,
                after.source_posterior.model_diagnostics)
            assert math.dist(after.source_posterior.posterior_mean_x_y, source) < .15
            after_median = np.nanmedian([np.nan if v is None else v for v in after.values_row_major])
            assert after_median == pytest.approx(before_median, rel=.15)
            field = np.asarray([np.nan if v is None else v for v in after.values_row_major])
            peak_y, peak_x = np.unravel_index(np.nanargmax(field), after.grid_shape)
            assert math.dist((after.x_coordinates_m[peak_x],
                              after.y_coordinates_m[peak_y]), source) < .75
            assert after.source_posterior.model_diagnostics["spatial_span_m"] == \
                geometry_before["spatial_span_m"]
            assert after.sample_count == sequence
            assert after.source_posterior.update_sequence == sequence
            assert after.exposure.cumulative_detector_dose_uSv == pytest.approx(total_dose)

    # Moving again continues acquisition and source localization normally.
    for position in [(8, 5.5), (8, 6.5), (7, 6.5), (7, 4.5), (8, 4.5)]:
        add(position)
    resumed = service.predict(sequence * 1_000_000_000, include_truth=False)
    assert resumed.metrics["reconstruction_mode"] == "physical_global"
    assert resumed.sample_count == len(positions) + 555
    assert math.dist(resumed.source_posterior.posterior_mean_x_y, source) < .15
    assert resumed.exposure.cumulative_detector_dose_uSv == pytest.approx(total_dose)
