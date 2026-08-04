"""Asynchronous simulated odometry source."""

from __future__ import annotations

import asyncio

import numpy as np

from ares_mapper.config import OdometryConfig
from ares_mapper.core.clock import SimulationClock
from ares_mapper.core.health import mark_sample, mark_stopped
from ares_mapper.core.transforms import yaw_to_quaternion
from ares_mapper.domain.enums import HealthState
from ares_mapper.domain.models import PoseSample, RunContext, SourceHealth
from ares_mapper.simulation.odometry import OdometryModel
from ares_mapper.simulation.trajectory import Trajectory


class SimulatedPoseSource:
    def __init__(
        self,
        config: OdometryConfig,
        trajectory: Trajectory,
        clock: SimulationClock,
        duration_s: float,
        seed: int,
    ) -> None:
        self.config = config
        self.trajectory = trajectory
        self.clock = clock
        self.duration_s = duration_s
        self.rng = np.random.Generator(np.random.PCG64(seed + 101))
        self.model = OdometryModel(config, self.rng)
        self._context: RunContext | None = None
        self._stop = asyncio.Event()
        self._health = SourceHealth(source_id="sim_odom")

    async def start(self, context: RunContext) -> None:
        self._context = context
        self._health.state = HealthState.HEALTHY
        self._stop.clear()

    async def samples(self):  # type: ignore[no-untyped-def]
        if self._context is None:
            raise RuntimeError("pose source has not been started")
        period_ns = int(1_000_000_000 / self.config.publish_rate_hz)
        duration_ns = int(self.duration_s * 1_000_000_000)
        source_time_ns = 0
        sequence = 0
        last_receive_ns = -1
        while source_time_ns <= duration_ns and not self._stop.is_set():
            jitter_ns = int(self.rng.normal(0.0, self.config.jitter_ms_std) * 1_000_000)
            receive_ns = max(
                source_time_ns + int(self.config.latency_ms * 1_000_000) + jitter_ns,
                last_receive_ns + 1,
            )
            await self.clock.wait_until(receive_ns)
            sequence += 1
            if self.rng.random() < self.config.dropout_probability:
                self._health.dropped_count += 1
                source_time_ns += period_ns
                continue
            truth = self.trajectory.pose_at(source_time_ns / 1_000_000_000)
            observed = self.model.measure(truth, source_time_ns / 1_000_000_000)
            qx, qy, qz, qw = yaw_to_quaternion(observed.yaw_rad)
            moving = abs(truth.vx_m_s) + abs(truth.vy_m_s) + abs(truth.yaw_rate_rad_s) > 1e-6
            sample = PoseSample(
                mission_id=self._context.mission_id,
                source_id="sim_odom",
                sequence=sequence,
                time_domain_id=self._context.time_domain_id,
                timeline_time_ns=source_time_ns,
                source_time_ns=source_time_ns,
                received_utc_ns=self.clock.utc_time_ns(),
                received_monotonic_ns=self.clock.monotonic_time_ns(),
                time_uncertainty_ns=max(
                    1,
                    int(max(0.0, self.config.jitter_ms_std) * 1_000_000),
                ),
                frame_id="world",
                child_frame_id="base",
                x_m=observed.x_m,
                y_m=observed.y_m,
                z_m=observed.z_m,
                qx=qx,
                qy=qy,
                qz=qz,
                qw=qw,
                yaw_rad=observed.yaw_rad,
                vx_m_s=truth.vx_m_s,
                vy_m_s=truth.vy_m_s,
                vz_m_s=truth.vz_m_s,
                yaw_rate_rad_s=truth.yaw_rate_rad_s,
                position_std_m=observed.position_std_m,
                yaw_std_rad=observed.yaw_std_rad,
                position_covariance=(
                    observed.position_std_m**2,
                    0.0,
                    0.0,
                    0.0,
                    observed.position_std_m**2,
                    0.0,
                    0.0,
                    0.0,
                    observed.position_std_m**2,
                ),
                orientation_covariance=(
                    observed.yaw_std_rad**2,
                    0.0,
                    0.0,
                    0.0,
                    observed.yaw_std_rad**2,
                    0.0,
                    0.0,
                    0.0,
                    observed.yaw_std_rad**2,
                ),
                quality=observed.quality,
                truth_x_m=truth.x_m,
                truth_y_m=truth.y_m,
                truth_z_m=truth.z_m,
                truth_yaw_rad=truth.yaw_rad,
                sport_mode=3 if moving else 1,
                gait_type=1 if moving else 0,
                foot_raise_height_m=0.08 if moving else 0.0,
                body_height_m=truth.z_m,
                range_obstacle_m=(
                    max(0.0, self.trajectory.world.bounds_m.x_max - truth.x_m),
                    max(0.0, self.trajectory.world.bounds_m.y_max - truth.y_m),
                    max(0.0, truth.x_m - self.trajectory.world.bounds_m.x_min),
                    max(0.0, truth.y_m - self.trajectory.world.bounds_m.y_min),
                ),
                foot_force_raw=(105, 105, 105, 105) if moving else (125, 125, 125, 125),
                foot_position_body_m=(
                    0.22,
                    -0.14,
                    -0.32,
                    0.22,
                    0.14,
                    -0.32,
                    -0.22,
                    -0.14,
                    -0.32,
                    -0.22,
                    0.14,
                    -0.32,
                ),
                foot_speed_body_m_s=(0.0,) * 12,
                imu_gyroscope_rad_s=(0.0, 0.0, truth.yaw_rate_rad_s),
                imu_accelerometer_m_s2=(0.0, 0.0, 9.81),
                imu_temperature_c=35,
            )
            mark_sample(self._health, receive_ns, sample.received_utc_ns)
            last_receive_ns = receive_ns
            yield sample
            source_time_ns += period_ns
        mark_stopped(self._health)

    async def stop(self) -> None:
        self._stop.set()
        mark_stopped(self._health)

    def health(self) -> SourceHealth:
        return self._health.model_copy(deep=True)
