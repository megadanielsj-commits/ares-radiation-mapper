"""Programmatic scenario event definitions."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ScheduledEvent:
    time_s: float
    event_type: str
    target_id: str
    values: dict[str, Any]
