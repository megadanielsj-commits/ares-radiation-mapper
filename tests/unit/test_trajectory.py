import math

import pytest

from ares_mapper.config import load_scenario
from ares_mapper.simulation.trajectory import Trajectory


def test_lawnmower_stays_inside_rectangle() -> None:
    scenario = load_scenario("config/scenarios/static_source.yaml")
    trajectory = Trajectory(scenario.trajectory, scenario.world, scenario.mission.seed, 120)
    rectangle = scenario.trajectory.rectangle_m
    for time_s in range(0, 121):
        pose = trajectory.pose_at(float(time_s))
        assert rectangle.x_min <= pose.x_m <= rectangle.x_max
        assert rectangle.y_min <= pose.y_m <= rectangle.y_max


def test_circle_has_constant_radius() -> None:
    scenario = load_scenario("config/scenarios/odometry_drift.yaml")
    trajectory = Trajectory(scenario.trajectory, scenario.world, scenario.mission.seed, 100)
    cx, cy, _ = scenario.trajectory.circle_center_m
    for time_s in (0.0, 1.0, 10.0, 42.0):
        pose = trajectory.pose_at(time_s)
        assert math.hypot(pose.x_m - cx, pose.y_m - cy) == pytest.approx(
            scenario.trajectory.circle_radius_m
        )


def test_manual_trajectory_integrates_forward_and_turn_commands() -> None:
    scenario = load_scenario("config/scenarios/static_source.yaml")
    trajectory = Trajectory(
        scenario.trajectory,
        scenario.world,
        scenario.mission.seed,
        20,
    )
    trajectory.set_manual_command(0.0, linear_m_s=0.5, yaw_rate_rad_s=0.0)
    forward = trajectory.pose_at(2.0)
    assert forward.x_m == pytest.approx(3.0)
    assert forward.y_m == pytest.approx(2.0)

    trajectory.set_manual_command(2.0, linear_m_s=0.0, yaw_rate_rad_s=math.pi / 2)
    turned = trajectory.pose_at(3.0)
    assert turned.x_m == pytest.approx(3.0)
    assert turned.yaw_rad == pytest.approx(math.pi / 2)

    trajectory.set_manual_command(3.0, linear_m_s=0.5, yaw_rate_rad_s=0.0)
    north = trajectory.pose_at(4.0)
    assert north.x_m == pytest.approx(3.0)
    assert north.y_m == pytest.approx(2.5)
