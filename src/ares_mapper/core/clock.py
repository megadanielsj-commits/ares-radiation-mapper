"""Clock abstractions used to keep simulation deterministic and controllable."""

from __future__ import annotations

import asyncio
import time
from contextlib import suppress
from typing import Protocol


class Clock(Protocol):
    def timeline_time_ns(self) -> int: ...

    def utc_time_ns(self) -> int: ...

    def monotonic_time_ns(self) -> int: ...


class RealClock:
    """Clock for future single-computer hardware acquisition."""

    def timeline_time_ns(self) -> int:
        return time.monotonic_ns()

    def utc_time_ns(self) -> int:
        return time.time_ns()

    def monotonic_time_ns(self) -> int:
        return time.monotonic_ns()


class SimulationClock:
    """Virtual monotonic clock with pause, step and speed controls."""

    def __init__(self, speed: float = 1.0) -> None:
        if speed <= 0:
            raise ValueError("simulation speed must be positive")
        self._speed = speed
        self._virtual_base_ns = 0
        self._wall_base_ns = time.monotonic_ns()
        self._paused = True
        self._stopped = False
        self._condition = asyncio.Condition()

    @property
    def speed(self) -> float:
        return self._speed

    @property
    def paused(self) -> bool:
        return self._paused

    def timeline_time_ns(self) -> int:
        if self._paused:
            return self._virtual_base_ns
        elapsed_wall_ns = time.monotonic_ns() - self._wall_base_ns
        return self._virtual_base_ns + int(elapsed_wall_ns * self._speed)

    def utc_time_ns(self) -> int:
        return time.time_ns()

    def monotonic_time_ns(self) -> int:
        return time.monotonic_ns()

    async def resume(self) -> None:
        async with self._condition:
            if self._stopped:
                raise RuntimeError("clock is stopped")
            if self._paused:
                self._wall_base_ns = time.monotonic_ns()
                self._paused = False
            self._condition.notify_all()

    async def pause(self) -> None:
        async with self._condition:
            if not self._paused:
                self._virtual_base_ns = self.timeline_time_ns()
                self._paused = True
            self._condition.notify_all()

    async def step(self, delta_ns: int) -> int:
        if delta_ns <= 0:
            raise ValueError("step must be positive")
        async with self._condition:
            if not self._paused:
                raise RuntimeError("step is only available while paused")
            self._virtual_base_ns += delta_ns
            self._condition.notify_all()
            return self._virtual_base_ns

    async def set_speed(self, speed: float) -> None:
        if speed <= 0:
            raise ValueError("simulation speed must be positive")
        async with self._condition:
            if not self._paused:
                self._virtual_base_ns = self.timeline_time_ns()
                self._wall_base_ns = time.monotonic_ns()
            self._speed = speed
            self._condition.notify_all()

    async def wait_until(self, target_time_ns: int) -> None:
        while True:
            async with self._condition:
                if self._stopped:
                    raise asyncio.CancelledError
                remaining_ns = target_time_ns - self.timeline_time_ns()
                if remaining_ns <= 0:
                    return
                if self._paused:
                    await self._condition.wait()
                    continue
                timeout_s = min(remaining_ns / 1_000_000_000 / self._speed, 0.1)
                # Python 3.10 raises asyncio.TimeoutError here.  Python 3.11+
                # aliases it to the built-in TimeoutError, so use the asyncio
                # name to keep the Docker image and local development aligned.
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._condition.wait(), timeout=timeout_s)

    async def stop(self) -> None:
        async with self._condition:
            if not self._paused:
                self._virtual_base_ns = self.timeline_time_ns()
            self._paused = True
            self._stopped = True
            self._condition.notify_all()
