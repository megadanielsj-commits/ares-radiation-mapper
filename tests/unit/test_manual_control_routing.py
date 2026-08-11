from __future__ import annotations

import pytest

from ares_mapper.config import load_scenario
from ares_mapper.core.mission_controller import MissionController
from ares_mapper.domain.enums import MissionState


class FakeCommander:
    def __init__(self) -> None:
        self.sent: list[tuple[float, float]] = []
        self.stop_calls = 0

    async def send(self, linear_m_s: float, yaw_rate_rad_s: float) -> None:
        self.sent.append((linear_m_s, yaw_rate_rad_s))

    async def stop(self) -> None:
        self.stop_calls += 1


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


async def test_finalize_halts_commander_on_fault() -> None:
    controller = _real_pose_controller()
    commander = FakeCommander()
    controller.sport_commander = commander
    controller.clock = None
    controller.map_service = None
    controller._finalized = False  # noqa: SLF001
    controller._stop_reason = "fault"  # noqa: SLF001
    controller._counts = {  # noqa: SLF001
        "pose": 0,
        "radiation": 0,
        "mapped": 0,
        "events": 0,
        "duplicates": 0,
        "unsynchronized": 0,
        "cumulative_recovery": 0,
    }

    await controller._finalize(MissionState.FAULT)  # noqa: SLF001

    assert commander.stop_calls == 1
