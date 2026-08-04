"""Optional Unitree SDK2 SportModeState pose source."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

from ares_mapper.config import PoseProviderConfig
from ares_mapper.core.clock import SimulationClock
from ares_mapper.core.health import mark_sample, mark_stopped
from ares_mapper.core.transforms import quaternion_to_yaw
from ares_mapper.domain.enums import HealthState, Quality
from ares_mapper.domain.models import PoseSample, RunContext, SourceHealth


class UnitreeSdk2PoseSource:
    """Bridges SDK2 callbacks into the provider-neutral pose contract."""

    def __init__(
        self,
        network_interface: str,
        domain_id: int = 0,
        topic: str = "rt/sportmodestate",
        *,
        config: PoseProviderConfig | None = None,
        clock: SimulationClock | None = None,
    ) -> None:
        self.config = config or PoseProviderConfig(
            provider="unitree_sportmode",
            network_interface=network_interface,
            domain_id=domain_id,
            topic=topic,
        )
        self.network_interface = network_interface
        self.domain_id = domain_id
        self.topic = topic
        self.clock = clock
        self._health = SourceHealth(source_id="unitree_sdk2_sportmode")
        self._context: RunContext | None = None
        self._queue: asyncio.Queue[tuple[Any, int, int]] = asyncio.Queue(maxsize=512)
        self._subscriber: Any = None
        self._stop = asyncio.Event()
        self._sequence = 0
        self._started_monotonic_ns = 0

    async def start(self, context: RunContext) -> None:
        self._context = context
        self._stop.clear()
        self._started_monotonic_ns = time.monotonic_ns()
        self._health.state = HealthState.STARTING
        loop = asyncio.get_running_loop()
        try:
            from unitree_sdk2py.core.channel import (
                ChannelFactoryInitialize,
                ChannelSubscriber,
            )
            from unitree_sdk2py.idl.unitree_go.msg.dds_ import (
                SportModeState_,
            )

            await asyncio.to_thread(
                ChannelFactoryInitialize,
                self.domain_id,
                self.network_interface,
            )
            subscriber = ChannelSubscriber(self.topic, SportModeState_)

            def callback(message: Any) -> None:
                receive_monotonic_ns = time.monotonic_ns()
                receive_utc_ns = time.time_ns()

                def enqueue() -> None:
                    if self._queue.full():
                        self._queue.get_nowait()
                        self._queue.task_done()
                        self._health.dropped_count += 1
                    self._queue.put_nowait((message, receive_monotonic_ns, receive_utc_ns))

                loop.call_soon_threadsafe(enqueue)

            await asyncio.to_thread(subscriber.Init, callback, 10)
            self._subscriber = subscriber
            self._health.state = HealthState.HEALTHY
        except Exception as exc:
            self._health.state = HealthState.FAULT
            self._health.last_error_code = type(exc).__name__
            self._health.last_error_message = str(exc)
            raise RuntimeError(
                "Unitree SDK2 provider requires unitree_sdk2py and a reachable "
                f"SportModeState topic ({self.topic}): {exc}"
            ) from exc

    async def samples(self) -> AsyncIterator[PoseSample]:
        if self._context is None:
            raise RuntimeError("Unitree pose source has not been started")
        while not self._stop.is_set():
            message, receive_monotonic_ns, receive_utc_ns = await self._queue.get()
            try:
                self._sequence += 1
                timeline_ns = (
                    self.clock.timeline_time_ns()
                    if self.clock is not None
                    else receive_monotonic_ns - self._started_monotonic_ns
                )
                sample = self.message_to_sample(
                    message,
                    self._context,
                    self._sequence,
                    timeline_ns,
                    receive_monotonic_ns,
                    receive_utc_ns,
                    self.config,
                )
                mark_sample(self._health, timeline_ns, receive_utc_ns)
                yield sample
            finally:
                self._queue.task_done()
        mark_stopped(self._health)

    async def stop(self) -> None:
        self._stop.set()
        subscriber = self._subscriber
        self._subscriber = None
        if subscriber is not None:
            close = getattr(subscriber, "Close", None)
            if close is not None:
                await asyncio.to_thread(close)
        mark_stopped(self._health)

    def health(self) -> SourceHealth:
        return self._health.model_copy(deep=True)

    @staticmethod
    def message_to_sample(
        message: Any,
        context: RunContext,
        sequence: int,
        timeline_ns: int,
        receive_monotonic_ns: int,
        receive_utc_ns: int,
        config: PoseProviderConfig,
    ) -> PoseSample:
        position = tuple(float(value) for value in message.position)
        velocity = tuple(float(value) for value in message.velocity)
        imu = message.imu_state
        quaternion = tuple(float(value) for value in imu.quaternion)
        qx, qy, qz, qw = quaternion[:4]
        yaw = quaternion_to_yaw(qx, qy, qz, qw)
        stamp = getattr(message, "stamp", None)
        source_time_ns = None
        if stamp is not None:
            seconds = getattr(stamp, "sec", getattr(stamp, "seconds", None))
            nanoseconds = getattr(stamp, "nanosec", getattr(stamp, "nanoseconds", 0))
            if seconds is not None:
                source_time_ns = int(seconds) * 1_000_000_000 + int(nanoseconds)
        covariance = (
            config.position_std_m**2,
            0.0,
            0.0,
            0.0,
            config.position_std_m**2,
            0.0,
            0.0,
            0.0,
            config.position_std_m**2,
        )
        yaw_covariance = (
            config.yaw_std_rad**2,
            0.0,
            0.0,
            0.0,
            config.yaw_std_rad**2,
            0.0,
            0.0,
            0.0,
            config.yaw_std_rad**2,
        )
        range_values = [float(value) for value in message.range_obstacle]
        force_values = [int(value) for value in message.foot_force]
        gyro_values = [float(value) for value in imu.gyroscope]
        acceleration_values = [float(value) for value in imu.accelerometer]
        return PoseSample(
            mission_id=context.mission_id,
            source_id="unitree_sdk2_sportmode",
            sequence=sequence,
            time_domain_id=context.time_domain_id,
            timeline_time_ns=timeline_ns,
            source_time_ns=source_time_ns,
            received_utc_ns=receive_utc_ns,
            received_monotonic_ns=receive_monotonic_ns,
            time_uncertainty_ns=20_000_000,
            frame_id=config.frame_id,
            child_frame_id=config.child_frame_id,
            x_m=position[0],
            y_m=position[1],
            z_m=position[2],
            qx=qx,
            qy=qy,
            qz=qz,
            qw=qw,
            yaw_rad=yaw,
            vx_m_s=velocity[0],
            vy_m_s=velocity[1],
            vz_m_s=velocity[2],
            yaw_rate_rad_s=float(message.yaw_speed),
            position_std_m=config.position_std_m,
            yaw_std_rad=config.yaw_std_rad,
            position_covariance=covariance,
            orientation_covariance=yaw_covariance,
            quality=Quality.VALID,
            error_code=int(message.error_code),
            sport_mode=int(message.mode),
            progress=float(message.progress),
            gait_type=int(message.gait_type),
            foot_raise_height_m=float(message.foot_raise_height),
            body_height_m=float(message.body_height),
            range_obstacle_m=(
                range_values[0],
                range_values[1],
                range_values[2],
                range_values[3],
            ),
            foot_force_raw=(
                force_values[0],
                force_values[1],
                force_values[2],
                force_values[3],
            ),
            foot_position_body_m=tuple(float(value) for value in message.foot_position_body),
            foot_speed_body_m_s=tuple(float(value) for value in message.foot_speed_body),
            imu_gyroscope_rad_s=(
                gyro_values[0],
                gyro_values[1],
                gyro_values[2],
            ),
            imu_accelerometer_m_s2=(
                acceleration_values[0],
                acceleration_values[1],
                acceleration_values[2],
            ),
            imu_temperature_c=int(imu.temperature),
            raw_payload={
                "mode": int(message.mode),
                "gait_type": int(message.gait_type),
                "observed_arrival_timeline_ns": timeline_ns,
            },
        )
