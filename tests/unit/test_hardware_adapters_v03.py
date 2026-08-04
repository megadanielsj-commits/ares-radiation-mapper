from __future__ import annotations

from types import SimpleNamespace

import pytest

from ares_mapper.adapters.unitree.ros2_tf_source import Ros2TfPoseSource
from ares_mapper.adapters.unitree.sdk2_source import UnitreeSdk2PoseSource
from ares_mapper.config import PoseProviderConfig
from ares_mapper.domain.models import RunContext


def _context() -> RunContext:
    return RunContext(
        mission_id="m",
        mode="real",
        time_domain_id="mission:m",
        seed=1,
        started_utc_ns=0,
    )


def test_ros_tf_transform_is_converted_without_truth_fields() -> None:
    config = PoseProviderConfig(
        provider="ros_tf",
        frame_id="map",
        child_frame_id="base_link",
        position_std_m=0.2,
        yaw_std_rad=0.1,
    )
    source = Ros2TfPoseSource("lo", config=config)
    source._context = _context()  # noqa: SLF001
    stamped = SimpleNamespace(
        header=SimpleNamespace(
            stamp=SimpleNamespace(sec=4, nanosec=5),
            frame_id="map",
        ),
        child_frame_id="base_link",
        transform=SimpleNamespace(
            translation=SimpleNamespace(x=1.0, y=2.0, z=0.32),
            rotation=SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0),
        ),
    )
    sample = source._to_sample(stamped, 10, 20, 30)  # noqa: SLF001
    assert sample.source_time_ns == 4_000_000_005
    assert sample.frame_id == "map"
    assert sample.child_frame_id == "base_link"
    assert sample.position_covariance[0] == pytest.approx(0.04)
    assert sample.truth_x_m is None


def test_unitree_sport_mode_contract_preserves_robot_telemetry() -> None:
    config = PoseProviderConfig(
        provider="unitree_sportmode",
        frame_id="odom",
        child_frame_id="base",
    )
    imu = SimpleNamespace(
        quaternion=[0.0, 0.0, 0.0, 1.0],
        gyroscope=[0.1, 0.2, 0.3],
        accelerometer=[0.0, 0.0, 9.81],
        temperature=37,
    )
    message = SimpleNamespace(
        position=[1.0, 2.0, 0.32],
        velocity=[0.4, 0.0, 0.0],
        imu_state=imu,
        stamp=SimpleNamespace(sec=8, nanosec=9),
        yaw_speed=0.2,
        error_code=0,
        mode=1,
        progress=0.5,
        gait_type=2,
        foot_raise_height=0.08,
        body_height=0.32,
        range_obstacle=[1.0, 2.0, 3.0, 4.0],
        foot_force=[10, 11, 12, 13],
        foot_position_body=[0.0] * 12,
        foot_speed_body=[0.0] * 12,
    )
    sample = UnitreeSdk2PoseSource.message_to_sample(
        message,
        _context(),
        sequence=1,
        timeline_ns=100,
        receive_monotonic_ns=200,
        receive_utc_ns=300,
        config=config,
    )
    assert sample.source_time_ns == 8_000_000_009
    assert sample.vx_m_s == pytest.approx(0.4)
    assert sample.imu_temperature_c == 37
    assert sample.range_obstacle_m == (1.0, 2.0, 3.0, 4.0)
    assert sample.foot_force_raw == (10, 11, 12, 13)
