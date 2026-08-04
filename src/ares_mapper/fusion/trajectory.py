"""Quadrature over an observed detector path."""

from __future__ import annotations

import math

from ares_mapper.config import SensorTransformConfig
from ares_mapper.core.transforms import apply_sensor_transform
from ares_mapper.domain.models import DetectorPathPoint, PoseSample


def quadrature_weights(times_ns: list[int]) -> list[float]:
    """Return trapezoidal point weights in seconds.

    The sum is exactly the elapsed integration duration, including irregular pose
    cadence. A single pose receives no duration because it cannot describe a path.
    """

    if not times_ns:
        return []
    if len(times_ns) == 1:
        return [0.0]
    if any(current <= previous for previous, current in zip(times_ns, times_ns[1:], strict=False)):
        raise ValueError("trajectory times must be strictly increasing")
    weights_ns = [0.0] * len(times_ns)
    weights_ns[0] = (times_ns[1] - times_ns[0]) / 2.0
    weights_ns[-1] = (times_ns[-1] - times_ns[-2]) / 2.0
    for index in range(1, len(times_ns) - 1):
        weights_ns[index] = (times_ns[index + 1] - times_ns[index - 1]) / 2.0
    return [weight / 1_000_000_000.0 for weight in weights_ns]


class TrajectoryIntegrator:
    """Transforms base poses into a detector path and computes path statistics."""

    def __init__(self, transform: SensorTransformConfig) -> None:
        self.transform = transform

    def detector_path(self, poses: list[PoseSample]) -> list[DetectorPathPoint]:
        points: list[DetectorPathPoint] = []
        lever_arm_m = math.hypot(
            self.transform.translation_m[0],
            self.transform.translation_m[1],
        )
        for pose in poses:
            x_m, y_m, z_m, yaw_rad = apply_sensor_transform(
                pose.x_m,
                pose.y_m,
                pose.z_m,
                pose.yaw_rad,
                self.transform,
            )
            points.append(
                DetectorPathPoint(
                    timeline_time_ns=pose.timeline_time_ns,
                    x_m=x_m,
                    y_m=y_m,
                    z_m=z_m,
                    yaw_rad=yaw_rad,
                    speed_m_s=(
                        math.hypot(pose.vx_m_s, pose.vy_m_s)
                        + abs(pose.yaw_rate_rad_s) * lever_arm_m
                    ),
                    position_std_m=max(0.0, float(pose.position_std_m or 0.0)),
                    time_uncertainty_ns=max(0, pose.time_uncertainty_ns),
                    pose_sequence_before=pose.sequence,
                    pose_sequence_after=pose.sequence,
                )
            )
        return points

    @staticmethod
    def path_length(points: list[DetectorPathPoint]) -> float:
        return sum(
            math.dist(
                (previous.x_m, previous.y_m, previous.z_m),
                (current.x_m, current.y_m, current.z_m),
            )
            for previous, current in zip(points, points[1:], strict=False)
        )

    @staticmethod
    def representative(
        points: list[DetectorPathPoint],
        weights_s: list[float],
    ) -> tuple[float, float, float, float]:
        if not points:
            raise ValueError("detector path cannot be empty")
        if len(points) != len(weights_s):
            raise ValueError("path and weights must have equal length")
        total = sum(weights_s)
        if total <= 0:
            point = points[len(points) // 2]
            return point.x_m, point.y_m, point.z_m, point.yaw_rad
        x_m = sum(point.x_m * weight for point, weight in zip(points, weights_s, strict=True))
        y_m = sum(point.y_m * weight for point, weight in zip(points, weights_s, strict=True))
        z_m = sum(point.z_m * weight for point, weight in zip(points, weights_s, strict=True))
        sin_yaw = sum(
            math.sin(point.yaw_rad) * weight
            for point, weight in zip(points, weights_s, strict=True)
        )
        cos_yaw = sum(
            math.cos(point.yaw_rad) * weight
            for point, weight in zip(points, weights_s, strict=True)
        )
        return x_m / total, y_m / total, z_m / total, math.atan2(sin_yaw, cos_yaw)
