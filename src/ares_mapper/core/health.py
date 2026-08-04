"""Helpers for source health accounting."""

from __future__ import annotations

from ares_mapper.domain.enums import HealthState
from ares_mapper.domain.models import SourceHealth


def mark_sample(health: SourceHealth, timeline_time_ns: int, utc_ns: int) -> None:
    previous_time_ns = health.last_sample_timeline_time_ns
    if previous_time_ns is not None and timeline_time_ns > previous_time_ns:
        instantaneous_rate_hz = 1_000_000_000 / (timeline_time_ns - previous_time_ns)
        health.observed_rate_hz = (
            instantaneous_rate_hz
            if health.observed_rate_hz <= 0
            else 0.9 * health.observed_rate_hz + 0.1 * instantaneous_rate_hz
        )
    health.received_count += 1
    health.last_sample_timeline_time_ns = timeline_time_ns
    health.last_receive_utc_ns = utc_ns
    health.state = HealthState.HEALTHY


def mark_stopped(health: SourceHealth) -> None:
    health.state = HealthState.STOPPED
