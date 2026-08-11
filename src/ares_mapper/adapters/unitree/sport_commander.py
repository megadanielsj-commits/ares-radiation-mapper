"""Send teleop velocity commands to a real Unitree Go2 via SDK2 SportClient."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from ares_mapper.adapters.unitree.channel_factory import ensure_channel_factory
from ares_mapper.core.health import mark_stopped
from ares_mapper.domain.enums import HealthState
from ares_mapper.domain.models import SourceHealth


def _default_client_factory() -> Any:
    from unitree_sdk2py.go2.sport.sport_client import SportClient

    client = SportClient()
    client.SetTimeout(10.0)
    client.Init()
    return client


class Go2SportCommander:
    """Translate UI teleop commands into Go2 SportClient Move/StopMove calls."""

    def __init__(
        self,
        network_interface: str,
        domain_id: int = 0,
        *,
        client_factory: Callable[[], Any] | None = None,
        channel_initializer: Callable[[int, str], None] | None = None,
    ) -> None:
        self.network_interface = network_interface
        self.domain_id = domain_id
        self._client_factory = client_factory or _default_client_factory
        self._channel_initializer = channel_initializer
        self._client: Any = None
        self._health = SourceHealth(source_id="unitree_sdk2_sport_commander")

    async def start(self) -> None:
        self._health.state = HealthState.STARTING
        try:
            await ensure_channel_factory(
                self.domain_id,
                self.network_interface,
                initializer=self._channel_initializer,
            )
            self._client = await asyncio.to_thread(self._client_factory)
            self._health.state = HealthState.HEALTHY
        except Exception as exc:
            self._health.state = HealthState.FAULT
            self._health.last_error_code = type(exc).__name__
            self._health.last_error_message = str(exc)
            raise

    async def send(self, linear_m_s: float, yaw_rate_rad_s: float) -> None:
        if self._client is None:
            raise RuntimeError("sport commander not started")
        try:
            if linear_m_s == 0.0 and yaw_rate_rad_s == 0.0:
                await asyncio.to_thread(self._client.StopMove)
            else:
                await asyncio.to_thread(
                    self._client.Move,
                    float(linear_m_s),
                    0.0,
                    float(yaw_rate_rad_s),
                )
        except Exception as exc:
            self._health.state = HealthState.FAULT
            self._health.last_error_code = type(exc).__name__
            self._health.last_error_message = str(exc)
            raise

    async def stop(self) -> None:
        if self._client is None:
            return
        try:
            await asyncio.to_thread(self._client.StopMove)
        except Exception as exc:  # keep teardown resilient
            self._health.last_error_code = type(exc).__name__
            self._health.last_error_message = str(exc)

    async def close(self) -> None:
        self._client = None
        mark_stopped(self._health)

    def health(self) -> SourceHealth:
        return self._health.model_copy(deep=True)
