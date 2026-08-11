from __future__ import annotations

import pytest

from ares_mapper.adapters.unitree import channel_factory


@pytest.fixture(autouse=True)
def _reset() -> None:
    channel_factory._reset_for_tests()  # noqa: SLF001
    yield
    channel_factory._reset_for_tests()  # noqa: SLF001


async def test_initializer_runs_only_once_for_same_params() -> None:
    calls: list[tuple[int, str]] = []

    def fake_init(domain_id: int, iface: str) -> None:
        calls.append((domain_id, iface))

    await channel_factory.ensure_channel_factory(0, "lo", initializer=fake_init)
    await channel_factory.ensure_channel_factory(0, "lo", initializer=fake_init)

    assert calls == [(0, "lo")]


async def test_conflicting_params_raise() -> None:
    def fake_init(domain_id: int, iface: str) -> None:
        return None

    await channel_factory.ensure_channel_factory(0, "lo", initializer=fake_init)
    with pytest.raises(RuntimeError, match="already initialized"):
        await channel_factory.ensure_channel_factory(1, "lo", initializer=fake_init)
