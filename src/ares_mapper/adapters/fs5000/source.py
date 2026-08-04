"""Read-only continuous serial source for the Bosean FS-5000."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Iterator
from typing import Any

from ares_mapper.adapters.fs5000.parser import parse_payload
from ares_mapper.config import DetectorConfig
from ares_mapper.core.clock import SimulationClock
from ares_mapper.core.health import mark_sample, mark_stopped
from ares_mapper.domain.enums import HealthState, Quality
from ares_mapper.domain.models import RadiationSample, RunContext, SourceHealth

_ITERATION_COMPLETE = object()


def _next_or_complete(iterator: Iterator[str]) -> str | object:
    try:
        return next(iterator)
    except StopIteration:
        return _ITERATION_COMPLETE


class FS5000SerialSource:
    """Streams validated packets and timestamps receipt with ``monotonic_ns``."""

    def __init__(
        self,
        port: str = "auto",
        *,
        config: DetectorConfig | None = None,
        clock: SimulationClock | None = None,
    ) -> None:
        self.config = config or DetectorConfig(
            sensor_id="fs5000_serial", source_type="fs5000_serial", serial_port=port
        )
        self.port = port
        self.clock = clock
        self._health = SourceHealth(source_id=self.config.sensor_id)
        self._context: RunContext | None = None
        self._device: Any = None
        self._iterator: Iterator[str] | None = None
        self._stop = asyncio.Event()
        self._started_monotonic_ns = 0

    async def start(self, context: RunContext) -> None:
        self._context = context
        self._stop.clear()
        self._health.state = HealthState.STARTING
        self._started_monotonic_ns = time.monotonic_ns()
        try:
            from ares_mapper.adapters.fs5000.vendor.fs5000 import FS5000, get_port

            resolved_port = await asyncio.to_thread(get_port) if self.port == "auto" else self.port
            self._device = await asyncio.to_thread(FS5000, resolved_port)
            self._iterator = self._device.yield_data()
            self._health.state = HealthState.HEALTHY
        except Exception as exc:
            self._health.state = HealthState.FAULT
            self._health.last_error_code = type(exc).__name__
            self._health.last_error_message = str(exc)
            raise RuntimeError(f"could not open FS-5000 on {self.port}: {exc}") from exc

    async def samples(self) -> AsyncIterator[RadiationSample]:
        if self._context is None or self._iterator is None:
            raise RuntimeError("FS-5000 source has not been started")
        sequence = 0
        period_ns = int(1_000_000_000 / self.config.publish_rate_hz)
        try:
            while not self._stop.is_set():
                row_or_complete = await asyncio.to_thread(_next_or_complete, self._iterator)
                if row_or_complete is _ITERATION_COMPLETE:
                    return
                row = str(row_or_complete)
                receive_monotonic_ns = time.monotonic_ns()
                receive_utc_ns = time.time_ns()
                payload_text = row.split(";", 1)[1] if ";" in row else row
                try:
                    payload = parse_payload(payload_text)
                except ValueError as exc:
                    self._health.invalid_count += 1
                    self._health.last_error_code = "INVALID_PACKET"
                    self._health.last_error_message = str(exc)
                    continue
                sequence += 1
                timeline_ns = (
                    self.clock.timeline_time_ns()
                    if self.clock is not None
                    else receive_monotonic_ns - self._started_monotonic_ns
                )
                integration_end_ns = timeline_ns
                integration_start_ns = max(0, integration_end_ns - period_ns)
                integration_s = max(
                    1e-6,
                    (integration_end_ns - integration_start_ns) / 1_000_000_000.0,
                )
                sample = RadiationSample(
                    mission_id=self._context.mission_id,
                    sensor_id=self.config.sensor_id,
                    sequence=sequence,
                    time_domain_id=self._context.time_domain_id,
                    timeline_time_ns=timeline_ns,
                    received_utc_ns=receive_utc_ns,
                    received_monotonic_ns=receive_monotonic_ns,
                    time_uncertainty_ns=50_000_000,
                    effective_measurement_time_ns=(integration_start_ns + integration_end_ns) // 2,
                    dose_rate_uSv_h=payload.dose_rate_uSv_h,
                    cumulative_dose_uSv=payload.cumulative_dose_uSv,
                    cps=payload.cps,
                    cpm=payload.cpm,
                    average_dose_rate_uSv_h=payload.average_dose_rate_uSv_h,
                    timer_s=payload.timer_s,
                    timed_dose_uSv=payload.timed_dose_uSv,
                    integration_time_s=integration_s,
                    integration_start_time_ns=integration_start_ns,
                    integration_end_time_ns=integration_end_ns,
                    latency_estimate_ms=0.0,
                    time_uncertainty_ms=50.0,
                    quality=Quality.VALID,
                    calibration_id=self.config.calibration_id,
                    alarm=payload.alarm,
                    raw_payload=payload.raw_payload,
                )
                mark_sample(
                    self._health,
                    timeline_ns,
                    receive_utc_ns,
                )
                yield sample
        finally:
            mark_stopped(self._health)

    async def stop(self) -> None:
        self._stop.set()
        iterator = self._iterator
        self._iterator = None
        if iterator is not None and hasattr(iterator, "close"):
            await asyncio.to_thread(iterator.close)
        device = self._device
        self._device = None
        if device is not None and hasattr(device, "port"):
            await asyncio.to_thread(device.port.close)
        mark_stopped(self._health)

    def health(self) -> SourceHealth:
        return self._health.model_copy(deep=True)
