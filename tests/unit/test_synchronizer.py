import math

import pytest

from ares_mapper.config import DetectorConfig, SensorTransformConfig, SynchronizationConfig
from ares_mapper.core.synchronizer import TemporalSynchronizer
from ares_mapper.core.transforms import yaw_to_quaternion
from ares_mapper.domain.models import PoseSample, RadiationSample


def pose(sequence: int, time_ns: int, x_m: float, yaw_rad: float) -> PoseSample:
    qx, qy, qz, qw = yaw_to_quaternion(yaw_rad)
    return PoseSample(
        mission_id="m",
        source_id="pose",
        sequence=sequence,
        time_domain_id="sim:m",
        timeline_time_ns=time_ns,
        source_time_ns=time_ns,
        received_utc_ns=time_ns,
        received_monotonic_ns=time_ns,
        x_m=x_m,
        y_m=0,
        z_m=0.32,
        qx=qx,
        qy=qy,
        qz=qz,
        qw=qw,
        yaw_rad=yaw_rad,
    )


def radiation(time_ns: int) -> RadiationSample:
    return RadiationSample(
        mission_id="m",
        sensor_id="detector",
        sequence=1,
        time_domain_id="sim:m",
        timeline_time_ns=time_ns,
        source_time_ns=time_ns,
        received_utc_ns=time_ns,
        received_monotonic_ns=time_ns,
        effective_measurement_time_ns=time_ns,
        dose_rate_uSv_h=1.0,
    )


def test_linear_interpolation_and_extrinsic_transform() -> None:
    sync = TemporalSynchronizer(
        SynchronizationConfig(),
        {"detector": SensorTransformConfig(translation_m=(1.0, 0.0, 0.25), rpy_rad=(0, 0, 0))},
    )
    sync.add_pose(pose(1, 0, 0, 0))
    sync.add_pose(pose(2, 1_000_000_000, 2, 0))
    mapped = sync.map_sample(radiation(500_000_000))
    assert mapped is not None
    assert mapped.base_x_m == pytest.approx(1.0)
    assert mapped.sensor_x_m == pytest.approx(2.0)


def test_yaw_interpolation_crosses_pi_on_short_arc() -> None:
    sync = TemporalSynchronizer(
        SynchronizationConfig(),
        {"detector": SensorTransformConfig()},
    )
    sync.add_pose(pose(1, 0, 0, math.radians(179)))
    sync.add_pose(pose(2, 1_000_000_000, 0, math.radians(-179)))
    mapped = sync.map_sample(radiation(500_000_000))
    assert mapped is not None
    assert abs(abs(mapped.sensor_yaw_rad) - math.pi) < math.radians(2)


def test_first_order_detector_response_is_aligned_with_its_effective_position() -> None:
    detector = DetectorConfig(
        sensor_id="detector",
        response_time_constant_s=1.0,
        response_compensation_enabled=True,
        response_uncertainty_scale=1.0,
    )
    sync = TemporalSynchronizer(
        SynchronizationConfig(max_pose_gap_ms=500),
        {"detector": SensorTransformConfig()},
        detectors={"detector": detector},
    )
    for sequence, quarter in enumerate(range(13), start=1):
        time_ns = quarter * 250_000_000
        sync.add_pose(
            pose(sequence, time_ns, quarter * 0.25, 0.0).model_copy(
                update={"vx_m_s": 1.0, "position_std_m": 0.01}
            )
        )

    first = radiation(1_000_000_000).model_copy(
        update={
            "sequence": 1,
            "effective_measurement_time_ns": 500_000_000,
            "integration_time_s": 1.0,
            "integration_start_time_ns": 0,
            "integration_end_time_ns": 1_000_000_000,
        }
    )
    second = radiation(2_000_000_000).model_copy(
        update={
            "sequence": 2,
            "effective_measurement_time_ns": 1_500_000_000,
            "integration_time_s": 1.0,
            "integration_start_time_ns": 1_000_000_000,
            "integration_end_time_ns": 2_000_000_000,
        }
    )
    first_window = sync.build_observation_window(first)
    second_window = sync.build_observation_window(second)

    assert first_window is not None
    assert first_window.response_delay_s == 0.0
    assert second_window is not None
    assert second_window.response_delay_s == pytest.approx(math.exp(-1.0))
    assert second_window.response_time_std_s == pytest.approx(
        math.sqrt(math.exp(-1.0) - math.exp(-2.0))
    )
    assert "DETECTOR_RESPONSE_COMPENSATED" in second_window.quality_flags
    mapped = sync.mapped_from_window(second_window, second)
    assert mapped.sensor_x_m == pytest.approx(1.5 - math.exp(-1.0), abs=0.01)
    assert mapped.position_std_m is not None
    assert mapped.position_std_m == pytest.approx(0.01)
