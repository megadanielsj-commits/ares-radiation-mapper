"""Replay radiation source preserving the recorded mission timeline."""

from __future__ import annotations

from collections.abc import AsyncIterator

from ares_mapper.core.clock import SimulationClock
from ares_mapper.domain.enums import HealthState
from ares_mapper.domain.models import RadiationSample, RunContext, SourceHealth


class ReplayRadiationSource:
    def __init__(self, samples: list[RadiationSample], clock: SimulationClock) -> None:
        self._samples = samples
        self._clock = clock
        self._stopped = False
        self._health = SourceHealth(source_id="replay_radiation")

    async def start(self, context: RunContext) -> None:
        del context
        self._stopped = False
        self._health.state = HealthState.HEALTHY

    async def samples(self) -> AsyncIterator[RadiationSample]:
        for sample in self._samples:
            if self._stopped:
                break
            await self._clock.wait_until(sample.timeline_time_ns)
            self._health.received_count += 1
            yield sample
        self._health.state = HealthState.STOPPED

    async def stop(self) -> None:
        self._stopped = True

    def health(self) -> SourceHealth:
        return self._health.model_copy(deep=True)
