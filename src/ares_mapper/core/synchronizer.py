"""Temporal fusion between asynchronous pose and radiological integrations."""

from __future__ import annotations

import bisect
import math
from collections import deque

from ares_mapper.config import DetectorConfig, SensorTransformConfig, SynchronizationConfig
from ares_mapper.core.transforms import quaternion_to_yaw, slerp
from ares_mapper.domain.enums import (
    EvidenceKind,
    MappingQuality,
    ObservationMode,
    Quality,
    SyncMethod,
)
from ares_mapper.domain.models import (
    MappedSample,
    ObservationWindow,
    PoseSample,
    RadiationSample,
)
from ares_mapper.fusion.trajectory import TrajectoryIntegrator, quadrature_weights


class TemporalSynchronizer:
    """Keeps bounded pose history and constructs detector-path observations."""

    def __init__(
        self,
        config: SynchronizationConfig,
        sensor_transforms: dict[str, SensorTransformConfig],
        buffer_duration_s: float = 120.0,
        detectors: dict[str, DetectorConfig] | None = None,
    ) -> None:
        self.config = config
        self.sensor_transforms = sensor_transforms
        self.detectors = detectors or {}
        self.buffer_duration_ns = int(buffer_duration_s * 1_000_000_000)
        self._poses: deque[PoseSample] = deque()
        self._response_moments: dict[str, tuple[int, float, float]] = {}
        self._mapped_sequence = 0
        self._observation_sequence = 0
        self.rejected_count = 0

    @property
    def pose_history_count(self) -> int:
        return len(self._poses)

    def add_pose(self, sample: PoseSample) -> None:
        if not self._poses or sample.timeline_time_ns >= self._poses[-1].timeline_time_ns:
            self._poses.append(sample)
        else:
            ordered = list(self._poses)
            times = [pose.timeline_time_ns for pose in ordered]
            ordered.insert(bisect.bisect_right(times, sample.timeline_time_ns), sample)
            self._poses = deque(ordered)
        newest = self._poses[-1].timeline_time_ns
        while self._poses and newest - self._poses[0].timeline_time_ns > self.buffer_duration_ns:
            self._poses.popleft()

    def build_observation_window(
        self,
        radiation: RadiationSample,
        observation_mode: ObservationMode | str = ObservationMode.DOSE_RATE_ROBUST,
        evidence_kind: EvidenceKind = EvidenceKind.INSTANTANEOUS,
    ) -> ObservationWindow | None:
        """Fuse one detector integration with all observed poses in its interval."""

        if not self._poses or radiation.time_domain_id != self._poses[-1].time_domain_id:
            self.rejected_count += 1
            return None
        point_compatibility = (
            radiation.integration_time_s is None
            and radiation.integration_start_time_ns is None
            and radiation.integration_end_time_ns is None
        )
        duration_s = max(1e-6, float(radiation.integration_time_s or 1.0))
        duration_ns = max(1, int(duration_s * 1_000_000_000))
        start_ns = radiation.integration_start_time_ns
        end_ns = radiation.integration_end_time_ns
        if point_compatibility:
            start_ns = radiation.effective_measurement_time_ns
            end_ns = radiation.effective_measurement_time_ns
        elif start_ns is None or end_ns is None or end_ns <= start_ns:
            half = duration_ns // 2
            start_ns = radiation.effective_measurement_time_ns - half
            end_ns = start_ns + duration_ns

        response_delay_s = 0.0
        response_time_std_s = 0.0
        response_state: tuple[int, float, float] | None = None
        if evidence_kind == EvidenceKind.INSTANTANEOUS and not point_compatibility:
            (
                start_ns,
                end_ns,
                response_delay_s,
                response_time_std_s,
                response_state,
            ) = self._response_adjusted_interval(
                radiation.sensor_id,
                start_ns,
                end_ns,
            )
        path_poses, maximum_gap_ms, boundary_sync_error_ms = self._poses_in_window(start_ns, end_ns)
        if path_poses is None:
            self.rejected_count += 1
            return None
        if response_state is not None:
            self._response_moments[radiation.sensor_id] = response_state
        transform = self.sensor_transforms.get(radiation.sensor_id, SensorTransformConfig())
        integrator = TrajectoryIntegrator(transform)
        detector_path = integrator.detector_path(path_poses)
        weights_s = quadrature_weights([point.timeline_time_ns for point in detector_path])
        if sum(weights_s) <= 0:
            weights_s = [duration_s / len(detector_path)] * len(detector_path)
        else:
            scale = duration_s / sum(weights_s)
            weights_s = [weight * scale for weight in weights_s]

        flags: list[str] = []
        quality = Quality.VALID
        if maximum_gap_ms > self.config.max_pose_gap_ms:
            self.rejected_count += 1
            return None
        if any(pose.quality != Quality.VALID for pose in path_poses):
            quality = Quality.DEGRADED
            flags.append("DEGRADED_POSE")
        if radiation.quality != Quality.VALID:
            quality = Quality.DEGRADED
            flags.append("DEGRADED_RADIATION")
        if boundary_sync_error_ms > 0:
            flags.append("INTERPOLATED_BOUNDARY")
        if maximum_gap_ms > 1000.0 / 10.0:
            flags.append("SPARSE_POSE_WINDOW")
        if response_delay_s > 0:
            flags.append("DETECTOR_RESPONSE_COMPENSATED")

        self._observation_sequence += 1
        safe_radiation = radiation.model_copy(
            update={
                "true_dose_rate_uSv_h": None,
                "true_sensor_x_m": None,
                "true_sensor_y_m": None,
                "true_sensor_z_m": None,
            }
        )
        covariances = [
            pose.position_covariance
            or (
                float(pose.position_std_m or 0.0) ** 2,
                0.0,
                0.0,
                0.0,
                float(pose.position_std_m or 0.0) ** 2,
                0.0,
                0.0,
                0.0,
                float(pose.position_std_m or 0.0) ** 2,
            )
            for pose in path_poses
        ]
        mode = (
            observation_mode
            if isinstance(observation_mode, ObservationMode)
            else ObservationMode(observation_mode)
        )
        return ObservationWindow(
            mission_id=radiation.mission_id,
            sensor_id=radiation.sensor_id,
            observation_sequence=self._observation_sequence,
            radiation_sample=safe_radiation,
            detector_path=detector_path,
            path_time_weights_s=weights_s,
            pose_covariances=covariances,
            extrinsic_transform={
                "translation_m": transform.translation_m,
                "rpy_rad": transform.rpy_rad,
            },
            integration_start_ns=start_ns,
            integration_end_ns=end_ns,
            integration_time_s=duration_s,
            maximum_pose_gap_ms=maximum_gap_ms,
            sync_error_ms=boundary_sync_error_ms
            + radiation.time_uncertainty_ns / 1_000_000.0
            + radiation.time_uncertainty_ms,
            response_delay_s=response_delay_s,
            response_time_std_s=response_time_std_s,
            observation_mode=mode,
            evidence_kind=evidence_kind,
            quality_flags=flags,
            quality=quality,
        )

    def _response_adjusted_interval(
        self,
        sensor_id: str,
        start_ns: int,
        end_ns: int,
    ) -> tuple[int, int, float, float, tuple[int, float, float] | None]:
        """Align a first-order detector response with its effective path.

        The detector response is a causal exponential average.  Its first temporal
        moment gives the effective delay, while the second moment becomes spatial
        uncertainty through the observed robot speed.  This avoids assigning a
        delayed high reading to the robot's newer position.
        """

        detector = self.detectors.get(sensor_id)
        if (
            detector is None
            or not detector.response_compensation_enabled
            or detector.response_time_constant_s <= 0
        ):
            return start_ns, end_ns, 0.0, 0.0, None

        previous = self._response_moments.get(sensor_id)
        if previous is None or end_ns <= previous[0]:
            state = (end_ns, 0.0, 0.0)
            return start_ns, end_ns, 0.0, 0.0, state

        delta_s = (end_ns - previous[0]) / 1_000_000_000.0
        retention = math.exp(-delta_s / detector.response_time_constant_s)
        previous_mean_s = previous[1]
        previous_second_moment_s2 = previous[2]
        mean_age_s = retention * (previous_mean_s + delta_s)
        second_moment_s2 = retention * (
            previous_second_moment_s2 + 2.0 * delta_s * previous_mean_s + delta_s * delta_s
        )
        variance_s2 = max(0.0, second_moment_s2 - mean_age_s * mean_age_s)
        time_std_s = math.sqrt(variance_s2)

        available_history_s = (
            max(0, start_ns - self._poses[0].timeline_time_ns) / 1_000_000_000.0
            if self._poses
            else 0.0
        )
        applied_delay_s = min(mean_age_s, available_history_s)
        if applied_delay_s < mean_age_s:
            time_std_s = math.hypot(time_std_s, mean_age_s - applied_delay_s)
        shift_ns = int(round(applied_delay_s * 1_000_000_000.0))
        state = (end_ns, mean_age_s, second_moment_s2)
        return (
            start_ns - shift_ns,
            end_ns - shift_ns,
            applied_delay_s,
            time_std_s,
            state,
        )

    def mapped_from_window(
        self,
        window: ObservationWindow,
        original_radiation: RadiationSample | None = None,
    ) -> MappedSample:
        """Create the legacy mapped contract from the integrated observation."""

        radiation = original_radiation or window.radiation_sample
        transform = self.sensor_transforms.get(window.sensor_id, SensorTransformConfig())
        integrator = TrajectoryIntegrator(transform)
        sensor_x, sensor_y, sensor_z, sensor_yaw = integrator.representative(
            window.detector_path, window.path_time_weights_s
        )
        target_ns = radiation.effective_measurement_time_ns
        base, before, after, sync_method, sync_error_ms = self._pose_at(target_ns)
        if base is None:
            base = list(self._poses)[-1]
            before = base
            after = base
            sync_method = SyncMethod.NEAREST
            sync_error_ms = window.sync_error_ms
        path_length_m = integrator.path_length(window.detector_path)
        velocity_path_length_m = sum(
            point.speed_m_s * weight
            for point, weight in zip(
                window.detector_path,
                window.path_time_weights_s,
                strict=True,
            )
        )
        if velocity_path_length_m > 0:
            path_length_m = velocity_path_length_m
        duration_s = max(window.integration_time_s, 1e-9)
        mapping_quality = (
            MappingQuality.VALID if window.quality == Quality.VALID else MappingQuality.DEGRADED
        )
        self._mapped_sequence += 1
        return MappedSample(
            mission_id=radiation.mission_id,
            mapped_sequence=self._mapped_sequence,
            radiation_sequence=radiation.sequence,
            sensor_id=radiation.sensor_id,
            time_domain_id=radiation.time_domain_id,
            pose_before_sequence=before.sequence if before else None,
            pose_after_sequence=after.sequence if after else None,
            effective_measurement_time_ns=target_ns,
            frame_id=base.frame_id,
            base_x_m=base.x_m,
            base_y_m=base.y_m,
            base_z_m=base.z_m,
            sensor_x_m=sensor_x,
            sensor_y_m=sensor_y,
            sensor_z_m=sensor_z,
            sensor_yaw_rad=sensor_yaw,
            dose_rate_uSv_h_raw=radiation.dose_rate_uSv_h,
            dose_rate_uSv_h_filtered=radiation.dose_rate_uSv_h,
            cumulative_dose_uSv=radiation.cumulative_dose_uSv,
            cps=radiation.cps,
            cpm=radiation.cpm,
            average_dose_rate_uSv_h=radiation.average_dose_rate_uSv_h,
            timer_s=radiation.timer_s,
            timed_dose_uSv=radiation.timed_dose_uSv,
            integration_time_s=window.integration_time_s,
            integration_start_time_ns=window.integration_start_ns,
            integration_end_time_ns=window.integration_end_ns,
            path_length_m=path_length_m,
            mean_speed_m_s=path_length_m / duration_s,
            dwell_time_s=duration_s if path_length_m <= 0.05 else 0.0,
            position_std_m=max(
                (point.position_std_m for point in window.detector_path),
                default=base.position_std_m,
            ),
            yaw_std_rad=base.yaw_std_rad,
            base_vx_m_s=base.vx_m_s,
            base_vy_m_s=base.vy_m_s,
            base_yaw_rate_rad_s=base.yaw_rate_rad_s,
            alarm=radiation.alarm,
            sync_method=sync_method,
            max_pose_gap_ms=window.maximum_pose_gap_ms,
            sync_error_estimate_ms=max(sync_error_ms, window.sync_error_ms),
            pose_quality=base.quality,
            radiation_quality=radiation.quality,
            mapping_quality=mapping_quality,
            flags=list(window.quality_flags),
            true_dose_rate_uSv_h=radiation.true_dose_rate_uSv_h,
            true_sensor_x_m=radiation.true_sensor_x_m,
            true_sensor_y_m=radiation.true_sensor_y_m,
            true_sensor_z_m=radiation.true_sensor_z_m,
        )

    def map_sample(self, radiation: RadiationSample) -> MappedSample | None:
        """Compatibility route used by V0.2 callers and old mission replays."""

        window = self.build_observation_window(radiation)
        if window is None:
            return None
        return self.mapped_from_window(window, radiation)

    def observed_poses_between(self, start_ns: int, end_ns: int) -> list[PoseSample]:
        """Return an observed path copy for provider-level mixed simulation."""

        poses, _, _ = self._poses_in_window(start_ns, end_ns)
        if poses is None:
            return []
        return [
            pose.model_copy(
                update={
                    "truth_x_m": None,
                    "truth_y_m": None,
                    "truth_z_m": None,
                    "truth_yaw_rad": None,
                    "is_ground_truth": False,
                }
            )
            for pose in poses
        ]

    def _poses_in_window(
        self, start_ns: int, end_ns: int
    ) -> tuple[list[PoseSample] | None, float, float]:
        start, _, _, _, start_error = self._pose_at(start_ns)
        end, _, _, _, end_error = self._pose_at(end_ns)
        if start is None or end is None:
            return None, float("inf"), float("inf")
        poses = [start]
        poses.extend(pose for pose in self._poses if start_ns < pose.timeline_time_ns < end_ns)
        poses.append(end)
        by_time = {pose.timeline_time_ns: pose for pose in poses}
        ordered = [by_time[time_ns] for time_ns in sorted(by_time)]
        maximum_gap_ms = max(
            (
                (current.timeline_time_ns - previous.timeline_time_ns) / 1_000_000.0
                for previous, current in zip(ordered, ordered[1:], strict=False)
            ),
            default=0.0,
        )
        return ordered, maximum_gap_ms, max(start_error, end_error)

    def _pose_at(
        self, target_ns: int
    ) -> tuple[
        PoseSample | None,
        PoseSample | None,
        PoseSample | None,
        SyncMethod,
        float,
    ]:
        poses = list(self._poses)
        times = [pose.timeline_time_ns for pose in poses]
        index = bisect.bisect_left(times, target_ns)
        before = poses[index - 1] if index > 0 else None
        after = poses[index] if index < len(poses) else None
        if after is not None and after.timeline_time_ns == target_ns:
            return after, after, after, SyncMethod.EXACT, 0.0
        if before is not None and after is not None:
            span_ns = after.timeline_time_ns - before.timeline_time_ns
            if span_ns <= 0:
                return before, before, after, SyncMethod.NEAREST, 0.0
            fraction = (target_ns - before.timeline_time_ns) / span_ns
            interpolated = self._interpolate_pose(before, after, fraction, target_ns)
            error_ms = (
                min(
                    target_ns - before.timeline_time_ns,
                    after.timeline_time_ns - target_ns,
                )
                / 1_000_000.0
            )
            return (
                interpolated,
                before,
                after,
                SyncMethod.LINEAR_SLERP,
                error_ms,
            )
        if not self.config.allow_nearest_fallback:
            return None, before, after, SyncMethod.NONE, float("inf")
        candidate = before if before is not None else after
        if candidate is None:
            return None, before, after, SyncMethod.NONE, float("inf")
        distance_ms = abs(candidate.timeline_time_ns - target_ns) / 1_000_000.0
        if distance_ms > self.config.nearest_fallback_max_ms:
            return None, before, after, SyncMethod.NONE, distance_ms
        nearest = candidate.model_copy(update={"timeline_time_ns": target_ns})
        return nearest, before, after, SyncMethod.NEAREST, distance_ms

    @staticmethod
    def _interpolate_pose(
        before: PoseSample,
        after: PoseSample,
        fraction: float,
        timeline_time_ns: int,
    ) -> PoseSample:
        fraction = min(1.0, max(0.0, fraction))
        q = slerp(
            (before.qx, before.qy, before.qz, before.qw),
            (after.qx, after.qy, after.qz, after.qw),
            fraction,
        )

        def linear(first: float, second: float) -> float:
            return first + fraction * (second - first)

        return before.model_copy(
            update={
                "timeline_time_ns": timeline_time_ns,
                "x_m": linear(before.x_m, after.x_m),
                "y_m": linear(before.y_m, after.y_m),
                "z_m": linear(before.z_m, after.z_m),
                "qx": q[0],
                "qy": q[1],
                "qz": q[2],
                "qw": q[3],
                "yaw_rad": quaternion_to_yaw(*q),
                "vx_m_s": linear(before.vx_m_s, after.vx_m_s),
                "vy_m_s": linear(before.vy_m_s, after.vy_m_s),
                "vz_m_s": linear(before.vz_m_s, after.vz_m_s),
                "yaw_rate_rad_s": linear(before.yaw_rate_rad_s, after.yaw_rate_rad_s),
                "position_std_m": max(
                    float(before.position_std_m or 0.0),
                    float(after.position_std_m or 0.0),
                ),
                "time_uncertainty_ns": max(before.time_uncertainty_ns, after.time_uncertainty_ns),
                "quality": (
                    Quality.VALID
                    if before.quality == after.quality == Quality.VALID
                    else Quality.DEGRADED
                ),
            }
        )
