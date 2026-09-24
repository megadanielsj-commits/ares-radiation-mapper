"""Read live, append-only records from the independent USB acquisition process."""
from __future__ import annotations

import asyncio
import json
import time

from ares_mapper.core.health import mark_sample, mark_stopped
from ares_mapper.domain.enums import HealthState, Quality
from ares_mapper.domain.models import RadiationSample, SourceHealth


class RadiacodeJsonlSource:
    def __init__(self, config, clock, duration_s):
        self.config, self.clock, self.duration_s = config, clock, duration_s
        self._health = SourceHealth(source_id=config.sensor_id)
        self._stop = asyncio.Event()
        self._stream = None
        self._context = None
        self._last_receive_ns = time.monotonic_ns()

    async def start(self, context):
        self._context = context
        self._stop.clear()
        if self.clock.speed != 1.0:
            raise ValueError("Aquisição real exige velocidade 1x")
        self._stream = self.config.live_jsonl_path.open(encoding="utf-8")
        # Old records remain in the recorder's files; never position them at 'now'.
        self._stream.seek(0, 2)
        self._health.state = HealthState.STARTING
        self._last_receive_ns = time.monotonic_ns()

    async def samples(self):
        previous_time = None
        previous_session = None
        while not self._stop.is_set():
            if self.clock.timeline_time_ns() >= self.duration_s * 1e9:
                break
            position = self._stream.tell()
            line = self._stream.readline()
            if not line.endswith("\n"):
                self._stream.seek(position)
                if time.monotonic_ns() - self._last_receive_ns > 5_000_000_000:
                    self._health.state = HealthState.DISCONNECTED
                    self._health.last_error_code = "NO_RECENT_USB_DATA"
                    self._health.last_error_message = "Sem leitura USB recente; conferir terminal do leitor"
                await asyncio.sleep(0.05)
                continue
            try:
                row = json.loads(line)
                if row.get("source") != "radiacode_usb" or row.get("kind") != "measurement":
                    raise ValueError("O arquivo não contém leituras USB Radiacode")
                if row.get("is_duplicate"):
                    self._health.dropped_count += 1
                    continue
                receipt = int(row["received_monotonic_ns"])
                now = time.monotonic_ns()
                age_ns = now - receipt
                timeline = self.clock.timeline_time_ns() - age_ns
                if age_ns < 0 or age_ns > 5_000_000_000 or timeline <= 0:
                    self._health.dropped_count += 1
                    continue
                session = row["session_id"]
                if previous_session not in (None, session):
                    raise ValueError("Sessão do leitor mudou: reinicie o painel")
                previous_session = session
                # Only a presentation interval, NOT a measured detector response time.
                period_ns = int(1e9 / self.config.publish_rate_hz)
                start = max(0, timeline - period_ns)
                if previous_time is not None:
                    start = max(start, previous_time)
                if timeline <= start:
                    self._health.dropped_count += 1
                    continue
                sample = RadiationSample(
                    mission_id=self._context.mission_id,
                    sensor_id=self.config.sensor_id, sequence=int(row["sequence"]),
                    time_domain_id=self._context.time_domain_id,
                    timeline_time_ns=timeline,
                    received_utc_ns=int(row["received_utc_ns"]),
                    received_monotonic_ns=receipt,
                    effective_measurement_time_ns=(start + timeline) // 2,
                    time_uncertainty_ns=500_000_000,
                    dose_rate_uSv_h=float(row["dose_rate_uSv_h"]),
                    cumulative_dose_uSv=None,
                    cps=float(row["cps"]), cpm=None,
                    integration_time_s=(timeline - start) / 1e9,
                    integration_start_time_ns=start, integration_end_time_ns=timeline,
                    time_uncertainty_ms=500.0, quality=Quality.DEGRADED,
                    calibration_id="radiacode-scale-unverified-virtual-position",
                    raw_payload=json.dumps(row, ensure_ascii=False),
                )
                previous_time = timeline
                self._last_receive_ns = receipt
                mark_sample(self._health, timeline, sample.received_utc_ns)
                yield sample
            except (ValueError, KeyError, TypeError) as exc:
                self._health.invalid_count += 1
                self._health.last_error_code = "INVALID_USB_RECORD"
                self._health.last_error_message = str(exc)
        mark_stopped(self._health)

    async def stop(self):
        self._stop.set()
        if self._stream is not None:
            self._stream.close()
        mark_stopped(self._health)

    def health(self):
        return self._health.model_copy(deep=True)
