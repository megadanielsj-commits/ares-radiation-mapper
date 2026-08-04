"""Simulated FS-5000 driven by a real or MuJoCo pose stream."""

from __future__ import annotations

import asyncio

import numpy as np

from ares_mapper.config import DetectorConfig
from ares_mapper.core.clock import SimulationClock
from ares_mapper.core.health import mark_sample, mark_stopped
from ares_mapper.core.synchronizer import TemporalSynchronizer
from ares_mapper.domain.enums import HealthState
from ares_mapper.domain.models import RadiationSample, RunContext, SourceHealth
from ares_mapper.fusion.trajectory import TrajectoryIntegrator
from ares_mapper.simulation.detector import DetectorModel
from ares_mapper.simulation.radiation_field import RadiationField


class PoseCoupledSimulatedRadiationSource:
    """Produces simulated radiation from the provider-neutral observed pose path."""

    def __init__(
        self,
        config: DetectorConfig,
        synchronizer: TemporalSynchronizer,
        field: RadiationField,
        clock: SimulationClock,
        duration_s: float,
        seed: int,
    ) -> None:
        self.config = config
        self.synchronizer = synchronizer
        self.field = field
        self.clock = clock
        self.duration_s = duration_s
        self.rng = np.random.Generator(np.random.PCG64(seed + 1709))
        self.model = DetectorModel(config, self.rng)
        self._context: RunContext | None = None
        self._stop = asyncio.Event()
        self._health = SourceHealth(source_id=config.sensor_id)

    async def start(self, context: RunContext) -> None:
        self._context = context
        self._stop.clear()
        self._health.state = HealthState.HEALTHY

    async def samples(self):  # type: ignore[no-untyped-def]
        if self._context is None:
            raise RuntimeError("pose-coupled source has not been started")
        period_s = 1.0 / self.config.publish_rate_hz
        period_ns = int(period_s * 1_000_000_000)
        end_ns = period_ns
        sequence = 0
        integrator = TrajectoryIntegrator(self.config.transform_base_sensor)
        while end_ns <= int(self.duration_s * 1_000_000_000) and not self._stop.is_set():
            await self.clock.wait_until(end_ns)
            poses = self.synchronizer.observed_poses_between(end_ns - period_ns, end_ns)
            if not poses:
                self._health.dropped_count += 1
                end_ns += period_ns
                continue
            detector_path = integrator.detector_path(poses)
            true_rates = [
                self.field.dose_rate(
                    point.x_m,
                    point.y_m,
                    point.z_m,
                    point.timeline_time_ns / 1_000_000_000.0,
                )
                for point in detector_path
            ]
            true_rate = float(np.mean(true_rates))
            reading = self.model.measure(true_rate, period_s)
            sequence += 1
            receive_ns = end_ns + int(self.config.fixed_latency_ms * 1_000_000)
            await self.clock.wait_until(receive_ns)
            raw = (
                f"DR:{reading.dose_rate_uSv_h:.2f}uSv/h;"
                f"D:{reading.cumulative_dose_uSv:.2f}uSv;"
                f"CPS:{reading.cps:04d};CPM:{reading.cpm:06d};"
                f"AVG:{reading.average_dose_rate_uSv_h:.2f}uSv/h;"
                f"DT:{int(end_ns / 1_000_000_000):07d};"
                f"S:{reading.cumulative_dose_uSv:.2f}uSv;"
                f"W:{int(reading.alarm)}"
            )
            sample = RadiationSample(
                mission_id=self._context.mission_id,
                sensor_id=self.config.sensor_id,
                sequence=sequence,
                time_domain_id=self._context.time_domain_id,
                timeline_time_ns=end_ns,
                source_time_ns=end_ns,
                received_utc_ns=self.clock.utc_time_ns(),
                received_monotonic_ns=self.clock.monotonic_time_ns(),
                time_uncertainty_ns=max(1, int(self.config.jitter_ms_std * 1_000_000)),
                effective_measurement_time_ns=end_ns - period_ns // 2,
                dose_rate_uSv_h=reading.dose_rate_uSv_h,
                cumulative_dose_uSv=reading.cumulative_dose_uSv,
                cps=reading.cps,
                cpm=reading.cpm,
                average_dose_rate_uSv_h=reading.average_dose_rate_uSv_h,
                timer_s=int(end_ns / 1_000_000_000),
                timed_dose_uSv=reading.cumulative_dose_uSv,
                integration_time_s=period_s,
                integration_start_time_ns=end_ns - period_ns,
                integration_end_time_ns=end_ns,
                latency_estimate_ms=self.config.fixed_latency_ms,
                time_uncertainty_ms=self.config.jitter_ms_std,
                calibration_id=self.config.calibration_id,
                quality=reading.quality,
                alarm=reading.alarm,
                raw_payload=raw,
                true_dose_rate_uSv_h=true_rate,
                true_sensor_x_m=float(np.mean([point.x_m for point in detector_path])),
                true_sensor_y_m=float(np.mean([point.y_m for point in detector_path])),
                true_sensor_z_m=float(np.mean([point.z_m for point in detector_path])),
            )
            mark_sample(self._health, end_ns, sample.received_utc_ns)
            yield sample
            end_ns += period_ns
        mark_stopped(self._health)

    async def stop(self) -> None:
        self._stop.set()
        mark_stopped(self._health)

    def health(self) -> SourceHealth:
        return self._health.model_copy(deep=True)
