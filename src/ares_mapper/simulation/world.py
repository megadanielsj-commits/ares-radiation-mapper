"""World facade kept separate from the radiation field for future obstacles."""

from dataclasses import dataclass

from ares_mapper.config import WorldConfig


@dataclass(frozen=True, slots=True)
class SimulatedWorld:
    config: WorldConfig
