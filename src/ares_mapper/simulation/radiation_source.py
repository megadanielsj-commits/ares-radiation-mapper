"""Asynchronous simulated radiation source."""

from __future__ import annotations

import asyncio

import numpy as np

from ares_mapper.config import DetectorConfig
from ares_mapper.core.clock import SimulationClock
from ares_mapper.core.health import mark_sample, mark_stopped
from ares_mapper.core.transforms import apply_sensor_transform
from ares_mapper.domain.enums import HealthState
from ares_mapper.domain.models import RadiationSample, RunContext, SourceHealth
from ares_mapper.simulation.detector import DetectorModel
from ares_mapper.simulation.radiation_field import RadiationField
from ares_mapper.simulation.trajectory import Trajectory


class SimulatedRadiationSource:
    def __init__(
        self,
        config: DetectorConfig,
        trajectory: Trajectory,
        field: RadiationField,
        clock: SimulationClock,
        duration_s: float,
        seed: int,
    ) -> None:
        self.config = config
        self.trajectory = trajectory
        self.field = field
        self.clock = clock
        self.duration_s = duration_s
        self.rng = np.random.Generator(np.random.PCG64(seed + 307))
        self.model = DetectorModel(config, self.rng)
        self._context: RunContext | None = None
        self._stop = asyncio.Event()
        self._health = SourceHealth(source_id=config.sensor_id)

    async def start(self, context: RunContext) -> None:
        self._context = context
        self._health.state = HealthState.HEALTHY
        self._stop.clear()

    async def samples(self):  # type: ignore[no-untyped-def]
        if self._context is None:
            raise RuntimeError("radiation source has not been started")
        period_s = 1.0 / self.config.publish_rate_hz
        period_ns = int(period_s * 1_000_000_000)
        duration_ns = int(self.duration_s * 1_000_000_000)
        measurement_ns = period_ns
        sequence = 0
        last_receive_ns = -1
        while measurement_ns <= duration_ns and not self._stop.is_set():
            measurement_s = measurement_ns / 1_000_000_000
            window_start_s = max(0.0, measurement_s - period_s)
            window_times_s = np.linspace(
                window_start_s,
                measurement_s,
                11,
            )
            sensor_states = []
            true_rates = []
            for sample_time_s in window_times_s:
                truth_pose = self.trajectory.pose_at(float(sample_time_s))
                sensor_state = apply_sensor_transform(
                    truth_pose.x_m,
                    truth_pose.y_m,
                    truth_pose.z_m,
                    truth_pose.yaw_rad,
                    self.config.transform_base_sensor,
                )
                sensor_states.append(sensor_state)
                true_rates.append(
                    self.field.dose_rate(
                        sensor_state[0],
                        sensor_state[1],
                        sensor_state[2],
                        float(sample_time_s),
                    )
                )
            true_rate = float(np.mean(true_rates))
            sensor_x = float(np.mean([item[0] for item in sensor_states]))
            sensor_y = float(np.mean([item[1] for item in sensor_states]))
            sensor_z = float(np.mean([item[2] for item in sensor_states]))
            reading = self.model.measure(true_rate, period_s)
            jitter_ns = int(self.rng.normal(0.0, self.config.jitter_ms_std) * 1_000_000)
            receive_ns = max(
                measurement_ns + int(self.config.fixed_latency_ms * 1_000_000) + jitter_ns,
                last_receive_ns + 1,
            )
            await self.clock.wait_until(receive_ns)
            sequence += 1
            if self.rng.random() < self.config.dropout_probability:
                self._health.dropped_count += 1
                measurement_ns += period_ns
                continue
            raw = (
                f"DR:{reading.dose_rate_uSv_h:.2f}uSv/h;"
                f"D:{reading.cumulative_dose_uSv:.2f}uSv;"
                f"CPS:{reading.cps:04d};CPM:{reading.cpm:06d};"
                f"AVG:{reading.average_dose_rate_uSv_h:.2f}uSv/h;"
                f"DT:{int(measurement_ns / 1_000_000_000):07d};"
                f"S:{reading.cumulative_dose_uSv:.2f}uSv;"
                f"W:{int(reading.alarm)}"
            )
            sample = RadiationSample(
                mission_id=self._context.mission_id,
                sensor_id=self.config.sensor_id,
                sequence=sequence,
                time_domain_id=self._context.time_domain_id,
                timeline_time_ns=measurement_ns,
                source_time_ns=measurement_ns,
                received_utc_ns=self.clock.utc_time_ns(),
                received_monotonic_ns=self.clock.monotonic_time_ns(),
                time_uncertainty_ns=max(
                    1,
                    int(max(0.0, self.config.jitter_ms_std) * 1_000_000),
                ),
                effective_measurement_time_ns=int(
                    0.5 * (window_start_s + measurement_s) * 1_000_000_000
                ),
                dose_rate_uSv_h=reading.dose_rate_uSv_h,
                cumulative_dose_uSv=reading.cumulative_dose_uSv,
                cps=reading.cps,
                cpm=reading.cpm,
                average_dose_rate_uSv_h=reading.average_dose_rate_uSv_h,
                timer_s=int(measurement_ns / 1_000_000_000),
                timed_dose_uSv=reading.cumulative_dose_uSv,
                integration_time_s=period_s,
                integration_start_time_ns=int(window_start_s * 1_000_000_000),
                integration_end_time_ns=measurement_ns,
                latency_estimate_ms=self.config.fixed_latency_ms,
                time_uncertainty_ms=max(1.0, self.config.jitter_ms_std),
                quality=reading.quality,
                calibration_id=self.config.calibration_id,
                alarm=reading.alarm,
                raw_payload=raw,
                true_dose_rate_uSv_h=true_rate,
                true_sensor_x_m=sensor_x,
                true_sensor_y_m=sensor_y,
                true_sensor_z_m=sensor_z,
            )
            mark_sample(self._health, receive_ns, sample.received_utc_ns)
            last_receive_ns = receive_ns
            yield sample
            if self.rng.random() < self.config.duplicate_probability:
                sequence += 1
                duplicate = sample.model_copy(update={"sequence": sequence, "is_duplicate": True})
                yield duplicate
            measurement_ns += period_ns
        mark_stopped(self._health)

    async def stop(self) -> None:
        self._stop.set()
        mark_stopped(self._health)

    def health(self) -> SourceHealth:
        return self._health.model_copy(deep=True)
