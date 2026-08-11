from __future__ import annotations

import pytest

from ares_mapper.config import load_scenario
from ares_mapper.core.mission_controller import MissionController


class FakeCommander:
    def __init__(self) -> None:
        self.sent: list[tuple[float, float]] = []

    async def send(self, linear_m_s: float, yaw_rate_rad_s: float) -> None:
        self.sent.append((linear_m_s, yaw_rate_rad_s))


def _real_pose_controller() -> MissionController:
    config = load_scenario("config/hardware/go2_only_simdetector.yaml")
    controller = MissionController(config)
    controller.mission_id = "m"
    controller._replay_time_ns = 0  # noqa: SLF001
    controller._counts = {"events": 0}  # noqa: SLF001
    controller._manual_command = {"linear_m_s": 0.0, "yaw_rate_rad_s": 0.0}  # noqa: SLF001
    controller.store = None
    return controller


async def test_real_pose_routes_to_commander() -> None:
    controller = _real_pose_controller()
    commander = FakeCommander()
    controller.sport_commander = commander
    event = await controller.manual_control(0.45, 0.9)
    assert commander.sent == [(0.45, 0.9)]
    assert event.new_value == {"linear_m_s": 0.45, "yaw_rate_rad_s": 0.9}


async def test_real_pose_without_commander_raises() -> None:
    controller = _real_pose_controller()
    controller.sport_commander = None
    with pytest.raises(RuntimeError, match="real teleop is not available"):
        await controller.manual_control(0.45, 0.0)
