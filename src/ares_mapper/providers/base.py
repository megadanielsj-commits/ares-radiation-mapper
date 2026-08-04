"""Stable interfaces implemented by simulators, replay, FS-5000 and Unitree adapters."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from ares_mapper.domain.models import PoseSample, RadiationSample, RunContext, SourceHealth


class PoseSource(Protocol):
    async def start(self, context: RunContext) -> None: ...

    def samples(self) -> AsyncIterator[PoseSample]: ...

    async def stop(self) -> None: ...

    def health(self) -> SourceHealth: ...


class RadiationSource(Protocol):
    async def start(self, context: RunContext) -> None: ...

    def samples(self) -> AsyncIterator[RadiationSample]: ...

    async def stop(self) -> None: ...

    def health(self) -> SourceHealth: ...
