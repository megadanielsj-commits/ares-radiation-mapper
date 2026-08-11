from __future__ import annotations

import asyncio
import threading
import time

import pytest

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


class ConcurrencyTrackingSportClient:
    """Records the max number of in-flight SDK calls observed at once."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._current = 0
        self.max_concurrent = 0

    def _record(self) -> None:
        with self._guard:
            self._current += 1
            self.max_concurrent = max(self.max_concurrent, self._current)
        time.sleep(0.02)
        with self._guard:
            self._current -= 1

    def Move(self, vx: float, vy: float, vyaw: float) -> None:
        self._record()

    def StopMove(self) -> None:
        self._record()


class RaisingSportClient:
    def __init__(self) -> None:
        self.halt_calls = 0

    def Move(self, vx: float, vy: float, vyaw: float) -> None:
        if vx == 0.0 and vy == 0.0 and vyaw == 0.0:
            self.halt_calls += 1
            return
        raise RuntimeError("move failed")

    def StopMove(self) -> None:
        raise AssertionError("StopMove must not be used on the hot path")


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


async def test_zero_command_halts_via_zero_move() -> None:
    commander, client = _commander_with_client()
    await commander.send(0.0, 0.0)
    assert client.moves == [(0.0, 0.0, 0.0)]
    assert client.stop_calls == 0


async def test_stop_halts_via_zero_move() -> None:
    commander, client = _commander_with_client()
    await commander.stop()
    assert client.moves == [(0.0, 0.0, 0.0)]
    assert client.stop_calls == 0


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
    # start() primes the API/lease handshake with zero-velocity Move calls so
    # the first real user command is not delayed.
    assert client.moves == [(0.0, 0.0, 0.0)] * 3
    channel_factory._reset_for_tests()  # noqa: SLF001


async def test_send_calls_are_serialized_never_concurrent() -> None:
    client = ConcurrencyTrackingSportClient()
    commander = Go2SportCommander("lo", 0, client_factory=lambda: client)
    commander._client = client  # noqa: SLF001

    commands = [
        commander.send(0.1, 0.0),
        commander.send(0.0, 0.0),
        commander.send(0.2, 0.1),
        commander.send(0.0, 0.0),
        commander.send(0.3, -0.1),
    ]
    await asyncio.gather(*commands)

    assert client.max_concurrent == 1


async def test_send_error_attempts_halt_before_reraising() -> None:
    client = RaisingSportClient()
    commander = Go2SportCommander("lo", 0, client_factory=lambda: client)
    commander._client = client  # noqa: SLF001

    with pytest.raises(RuntimeError, match="move failed"):
        await commander.send(0.45, 0.0)

    assert client.halt_calls == 1
    assert commander.health().state is HealthState.FAULT
