from __future__ import annotations

from ares_mapper.adapters.unitree.sport_commander import Go2SportCommander
from ares_mapper.domain.enums import HealthState


class FakeSportClient:
    def __init__(self) -> None:
        self.moves: list[tuple[float, float, float]] = []
        self.stop_calls = 0

    def Move(self, vx: float, vy: float, vyaw: float) -> None:
        self.moves.append((vx, vy, vyaw))

    def StopMove(self) -> None:
        self.stop_calls += 1


def _commander_with_client() -> tuple[Go2SportCommander, FakeSportClient]:
    client = FakeSportClient()
    commander = Go2SportCommander("lo", 0, client_factory=lambda: client)
    commander._client = client  # noqa: SLF001
    return commander, client


async def test_forward_command_calls_move_with_zero_strafe() -> None:
    commander, client = _commander_with_client()
    await commander.send(0.45, 0.0)
    assert client.moves == [(0.45, 0.0, 0.0)]
    assert client.stop_calls == 0


async def test_yaw_command_maps_to_vyaw() -> None:
    commander, client = _commander_with_client()
    await commander.send(0.0, 0.9)
    assert client.moves == [(0.0, 0.0, 0.9)]


async def test_zero_command_calls_stopmove_not_move() -> None:
    commander, client = _commander_with_client()
    await commander.send(0.0, 0.0)
    assert client.moves == []
    assert client.stop_calls == 1


async def test_stop_calls_stopmove() -> None:
    commander, client = _commander_with_client()
    await commander.stop()
    assert client.stop_calls == 1


async def test_start_initializes_channel_and_client() -> None:
    init_calls: list[tuple[int, str]] = []
    client = FakeSportClient()
    from ares_mapper.adapters.unitree import channel_factory

    channel_factory._reset_for_tests()  # noqa: SLF001
    commander = Go2SportCommander(
        "lo",
        0,
        client_factory=lambda: client,
        channel_initializer=lambda d, i: init_calls.append((d, i)),
    )
    await commander.start()
    assert init_calls == [(0, "lo")]
    assert commander.health().state is HealthState.HEALTHY
    channel_factory._reset_for_tests()  # noqa: SLF001
