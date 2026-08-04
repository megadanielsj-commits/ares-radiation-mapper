"""Optional ROS 2 TF pose source for a SLAM-corrected ``map -> base`` transform."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import AsyncIterator
from typing import Any

from ares_mapper.config import PoseProviderConfig
from ares_mapper.core.clock import SimulationClock
from ares_mapper.core.health import mark_sample, mark_stopped
from ares_mapper.core.transforms import quaternion_to_yaw
from ares_mapper.domain.enums import HealthState, Quality
from ares_mapper.domain.models import PoseSample, RunContext, SourceHealth


class Ros2TfPoseSource:
    """Reads the latest configured TF transform at a bounded cadence."""

    def __init__(
        self,
        network_interface: str,
        domain_id: int = 0,
        topic: str = "/tf",
        *,
        config: PoseProviderConfig | None = None,
        clock: SimulationClock | None = None,
    ) -> None:
        self.config = config or PoseProviderConfig(
            provider="ros_tf",
            network_interface=network_interface,
            domain_id=domain_id,
            topic=topic,
        )
        self.network_interface = network_interface
        self.domain_id = domain_id
        self.clock = clock
        self._health = SourceHealth(source_id="ros2_tf")
        self._context: RunContext | None = None
        self._queue: asyncio.Queue[tuple[Any, int, int] | None] = asyncio.Queue(maxsize=512)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._node: Any = None
        self._listener: Any = None
        self._timer: Any = None
        self._executor: Any = None
        self._spin_thread: threading.Thread | None = None
        self._rclpy: Any = None
        self._stop = asyncio.Event()
        self._sequence = 0
        self._started_monotonic_ns = 0
        self._previous_sample: PoseSample | None = None

    async def start(self, context: RunContext) -> None:
        self._context = context
        self._stop.clear()
        self._loop = asyncio.get_running_loop()
        self._started_monotonic_ns = time.monotonic_ns()
        self._health.state = HealthState.STARTING
        try:
            import rclpy
            from rclpy.executors import SingleThreadedExecutor
            from rclpy.time import Time
            from tf2_ros import Buffer, TransformException, TransformListener

            await asyncio.to_thread(
                rclpy.init,
                args=None,
                domain_id=self.domain_id,
            )
            node = rclpy.create_node("ares_radiation_mapper_tf_source")
            buffer = Buffer()
            listener = TransformListener(buffer, node, spin_thread=False)

            def sample_transform() -> None:
                if self._stop.is_set() or self._loop is None:
                    return
                try:
                    transform = buffer.lookup_transform(
                        self.config.frame_id,
                        self.config.child_frame_id,
                        Time(),
                    )
                except TransformException as exc:
                    self._health.invalid_count += 1
                    self._health.last_error_code = "TF_LOOKUP"
                    self._health.last_error_message = str(exc)
                    return
                received_monotonic_ns = time.monotonic_ns()
                received_utc_ns = time.time_ns()

                def enqueue() -> None:
                    if self._queue.full():
                        self._queue.get_nowait()
                        self._queue.task_done()
                        self._health.dropped_count += 1
                    self._queue.put_nowait((transform, received_monotonic_ns, received_utc_ns))

                self._loop.call_soon_threadsafe(enqueue)

            timer = node.create_timer(
                1.0 / self.config.output_rate_hz,
                sample_transform,
            )
            executor = SingleThreadedExecutor()
            executor.add_node(node)
            spin_thread = threading.Thread(
                target=executor.spin,
                name="ares-ros2-tf",
                daemon=True,
            )
            spin_thread.start()
            self._rclpy = rclpy
            self._node = node
            self._listener = listener
            self._timer = timer
            self._executor = executor
            self._spin_thread = spin_thread
            self._health.state = HealthState.HEALTHY
        except Exception as exc:
            self._health.state = HealthState.FAULT
            self._health.last_error_code = type(exc).__name__
            self._health.last_error_message = str(exc)
            raise RuntimeError(
                "ROS TF provider requires rclpy, tf2_ros and a reachable "
                f"{self.config.frame_id} -> {self.config.child_frame_id} transform: "
                f"{exc}"
            ) from exc

    async def samples(self) -> AsyncIterator[PoseSample]:
        if self._context is None:
            raise RuntimeError("ROS TF pose source has not been started")
        while not self._stop.is_set():
            item = await self._queue.get()
            try:
                if item is None:
                    return
                transform, receive_monotonic_ns, receive_utc_ns = item
                self._sequence += 1
                timeline_ns = (
                    self.clock.timeline_time_ns()
                    if self.clock is not None
                    else receive_monotonic_ns - self._started_monotonic_ns
                )
                sample = self._to_sample(
                    transform,
                    timeline_ns,
                    receive_monotonic_ns,
                    receive_utc_ns,
                )
                mark_sample(self._health, timeline_ns, receive_utc_ns)
                self._previous_sample = sample
                yield sample
            finally:
                self._queue.task_done()
        mark_stopped(self._health)

    def _to_sample(
        self,
        stamped: Any,
        timeline_ns: int,
        receive_monotonic_ns: int,
        receive_utc_ns: int,
    ) -> PoseSample:
        assert self._context is not None
        translation = stamped.transform.translation
        rotation = stamped.transform.rotation
        source_time_ns = int(stamped.header.stamp.sec) * 1_000_000_000 + int(
            stamped.header.stamp.nanosec
        )
        delta_s = 0.0
        previous = self._previous_sample
        if previous is not None:
            delta_s = max(
                0.0,
                (timeline_ns - previous.timeline_time_ns) / 1_000_000_000.0,
            )
        vx = (
            (float(translation.x) - previous.x_m) / delta_s
            if previous is not None and delta_s > 0
            else 0.0
        )
        vy = (
            (float(translation.y) - previous.y_m) / delta_s
            if previous is not None and delta_s > 0
            else 0.0
        )
        vz = (
            (float(translation.z) - previous.z_m) / delta_s
            if previous is not None and delta_s > 0
            else 0.0
        )
        yaw = quaternion_to_yaw(
            float(rotation.x),
            float(rotation.y),
            float(rotation.z),
            float(rotation.w),
        )
        yaw_rate = (
            _wrapped_angle(yaw - previous.yaw_rad) / delta_s
            if previous is not None and delta_s > 0
            else 0.0
        )
        position_variance = self.config.position_std_m**2
        yaw_variance = self.config.yaw_std_rad**2
        return PoseSample(
            mission_id=self._context.mission_id,
            source_id="ros2_tf",
            sequence=self._sequence,
            time_domain_id=self._context.time_domain_id,
            timeline_time_ns=timeline_ns,
            source_time_ns=source_time_ns,
            received_utc_ns=receive_utc_ns,
            received_monotonic_ns=receive_monotonic_ns,
            time_uncertainty_ns=int(0.5e9 / self.config.output_rate_hz),
            frame_id=self.config.frame_id,
            child_frame_id=self.config.child_frame_id,
            x_m=float(translation.x),
            y_m=float(translation.y),
            z_m=float(translation.z),
            qx=float(rotation.x),
            qy=float(rotation.y),
            qz=float(rotation.z),
            qw=float(rotation.w),
            yaw_rad=yaw,
            vx_m_s=vx,
            vy_m_s=vy,
            vz_m_s=vz,
            yaw_rate_rad_s=yaw_rate,
            position_std_m=self.config.position_std_m,
            yaw_std_rad=self.config.yaw_std_rad,
            position_covariance=(
                position_variance,
                0.0,
                0.0,
                0.0,
                position_variance,
                0.0,
                0.0,
                0.0,
                position_variance,
            ),
            orientation_covariance=(
                yaw_variance,
                0.0,
                0.0,
                0.0,
                yaw_variance,
                0.0,
                0.0,
                0.0,
                yaw_variance,
            ),
            quality=Quality.VALID,
            raw_payload={
                "parent_frame": stamped.header.frame_id,
                "child_frame": stamped.child_frame_id,
            },
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._queue.empty():
            self._queue.put_nowait(None)
        timer = self._timer
        self._timer = None
        if timer is not None:
            timer.cancel()
        executor = self._executor
        self._executor = None
        if executor is not None:
            await asyncio.to_thread(executor.shutdown, timeout_sec=2.0)
        spin_thread = self._spin_thread
        self._spin_thread = None
        if spin_thread is not None:
            await asyncio.to_thread(spin_thread.join, 2.0)
        node = self._node
        self._node = None
        self._listener = None
        if node is not None:
            await asyncio.to_thread(node.destroy_node)
        rclpy = self._rclpy
        self._rclpy = None
        if rclpy is not None and rclpy.ok():
            await asyncio.to_thread(rclpy.shutdown)
        mark_stopped(self._health)

    def health(self) -> SourceHealth:
        return self._health.model_copy(deep=True)


def _wrapped_angle(value: float) -> float:
    while value > 3.141592653589793:
        value -= 2.0 * 3.141592653589793
    while value < -3.141592653589793:
        value += 2.0 * 3.141592653589793
    return value
