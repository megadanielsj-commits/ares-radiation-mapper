"""Replay real FS-5000-shaped CSV data against a simulated trajectory."""

from __future__ import annotations

import asyncio
import csv
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path

from ares_mapper.config import DetectorConfig
from ares_mapper.core.clock import SimulationClock
from ares_mapper.core.health import mark_sample, mark_stopped
from ares_mapper.domain.enums import HealthState, Quality
from ares_mapper.domain.models import RadiationSample, RunContext, SourceHealth


class CsvRadiationSource:
    """Read-only processing test; CSV values have no physical link to virtual positions."""

    def __init__(
        self,
        config: DetectorConfig,
        clock: SimulationClock,
        duration_s: float,
    ) -> None:
        self.config = config
        self.clock = clock
        self.duration_s = duration_s
        self._context: RunContext | None = None
        self._stop = asyncio.Event()
        self._health = SourceHealth(source_id=config.sensor_id)
        self._rows = self._load_rows(config.replay_csv_path)

    async def start(self, context: RunContext) -> None:
        self._context = context
        self._stop.clear()
        self._health.state = HealthState.HEALTHY

    async def samples(self) -> AsyncIterator[RadiationSample]:
        if self._context is None:
            raise RuntimeError("CSV radiation source has not been started")
        if not self._rows:
            self._health.state = HealthState.FAULT
            return
        first_timestamp = datetime.fromisoformat(self._rows[0]["timestamp"])
        previous_time_ns = 0
        for sequence, row in enumerate(self._rows, start=1):
            if self._stop.is_set():
                break
            timestamp = datetime.fromisoformat(row["timestamp"])
            source_relative_ns = int((timestamp - first_timestamp).total_seconds() * 1_000_000_000)
            relative_ns = max(source_relative_ns + 1_000_000_000, previous_time_ns + 1)
            if relative_ns > int(self.duration_s * 1_000_000_000):
                break
            await self.clock.wait_until(relative_ns)
            sample = RadiationSample(
                mission_id=self._context.mission_id,
                sensor_id=self.config.sensor_id,
                sequence=sequence,
                time_domain_id=self._context.time_domain_id,
                timeline_time_ns=relative_ns,
                source_time_ns=relative_ns,
                received_utc_ns=self.clock.utc_time_ns(),
                received_monotonic_ns=self.clock.monotonic_time_ns(),
                time_uncertainty_ns=500_000_000,
                effective_measurement_time_ns=relative_ns - 500_000_000,
                dose_rate_uSv_h=float(row["DR_uSv_h"]),
                cumulative_dose_uSv=float(row["D_uSv"]),
                cps=int(row["CPS"]),
                cpm=int(row["CPM"]),
                average_dose_rate_uSv_h=float(row["AVG_uSv_h"]),
                timer_s=int(row["DT"]) if row.get("DT") else None,
                timed_dose_uSv=float(row["S_uSv"]) if row.get("S_uSv") else None,
                integration_time_s=1.0,
                integration_start_time_ns=relative_ns - 1_000_000_000,
                integration_end_time_ns=relative_ns,
                latency_estimate_ms=0.0,
                time_uncertainty_ms=500.0,
                quality=Quality.VALID,
                calibration_id=self.config.calibration_id,
                alarm=bool(int(row["W"])),
                raw_payload=";".join(f"{key}:{value}" for key, value in row.items()),
            )
            mark_sample(self._health, relative_ns, sample.received_utc_ns)
            yield sample
            previous_time_ns = relative_ns
        mark_stopped(self._health)

    async def stop(self) -> None:
        self._stop.set()
        mark_stopped(self._health)

    def health(self) -> SourceHealth:
        return self._health.model_copy(deep=True)

    @staticmethod
    def _load_rows(path: Path | None) -> list[dict[str, str]]:
        if path is None:
            return []
        with path.open(newline="", encoding="utf-8-sig") as stream:
            return list(csv.DictReader(stream))
