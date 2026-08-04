"""Ground-truth robot trajectories."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ares_mapper.config import (
    UNITREE_GO2_STANDING_LENGTH_M,
    UNITREE_GO2_STANDING_WIDTH_M,
    TrajectoryConfig,
    WorldConfig,
)
from ares_mapper.domain.validation import normalize_yaw


@dataclass(frozen=True, slots=True)
class GroundTruthPose:
    x_m: float
    y_m: float
    z_m: float
    yaw_rad: float
    vx_m_s: float = 0.0
    vy_m_s: float = 0.0
    vz_m_s: float = 0.0
    yaw_rate_rad_s: float = 0.0


@dataclass(frozen=True, slots=True)
class _Segment:
    start_s: float
    end_s: float
    start: tuple[float, float, float]
    end: tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class _ManualControl:
    time_s: float
    linear_m_s: float
    yaw_rate_rad_s: float


class Trajectory:
    def __init__(
        self,
        config: TrajectoryConfig,
        world: WorldConfig,
        seed: int,
        duration_s: float,
    ) -> None:
        self.config = config
        self.world = world
        self.seed = seed
        self.duration_s = duration_s
        self._segments = self._build_segments()
        self._total_path_time_s = self._segments[-1].end_s if self._segments else 0.0
        self._random_points = self._build_random_walk() if config.type == "random_walk" else []
        self._manual_controls = [_ManualControl(0.0, 0.0, 0.0)]

    def pose_at(self, time_s: float) -> GroundTruthPose:
        time_s = max(0.0, time_s)
        if self.config.type == "circle":
            return self._circle_pose(time_s)
        if self.config.type == "manual":
            return self._manual_pose(time_s)
        if self.config.type == "stationary":
            x, y, z = self.config.start_m
            return GroundTruthPose(x, y, z, self.config.yaw_start_rad)
        if self.config.type == "scripted":
            return self._scripted_pose(time_s)
        if self.config.type == "random_walk":
            return self._random_walk_pose(time_s)
        return self._segmented_pose(time_s)

    def set_speed(self, speed_m_s: float) -> None:
        if speed_m_s <= 0:
            raise ValueError("speed must be positive")
        self.config.speed_m_s = speed_m_s
        self._segments = self._build_segments()
        self._total_path_time_s = self._segments[-1].end_s if self._segments else 0.0

    def set_manual_command(
        self,
        time_s: float,
        linear_m_s: float,
        yaw_rate_rad_s: float,
    ) -> None:
        if self.config.type != "manual":
            raise RuntimeError("manual commands require a manual trajectory")
        event = _ManualControl(
            max(0.0, float(time_s)),
            float(linear_m_s),
            float(yaw_rate_rad_s),
        )
        if abs(self._manual_controls[-1].time_s - event.time_s) < 1e-9:
            self._manual_controls[-1] = event
        elif (
            self._manual_controls[-1].linear_m_s != event.linear_m_s
            or self._manual_controls[-1].yaw_rate_rad_s != event.yaw_rate_rad_s
        ):
            self._manual_controls.append(event)

    def _manual_pose(self, time_s: float) -> GroundTruthPose:
        x, y, z = self.config.start_m
        yaw = self.config.yaw_start_rad
        active = self._manual_controls[0]
        cursor_s = 0.0
        for event in self._manual_controls[1:]:
            if event.time_s > time_s:
                break
            x, y, yaw = self._integrate_manual(
                x,
                y,
                yaw,
                active,
                max(0.0, event.time_s - cursor_s),
            )
            cursor_s = event.time_s
            active = event
        x, y, yaw = self._integrate_manual(
            x,
            y,
            yaw,
            active,
            max(0.0, time_s - cursor_s),
        )
        return GroundTruthPose(
            x_m=x,
            y_m=y,
            z_m=z,
            yaw_rad=yaw,
            vx_m_s=active.linear_m_s * math.cos(yaw),
            vy_m_s=active.linear_m_s * math.sin(yaw),
            yaw_rate_rad_s=active.yaw_rate_rad_s,
        )

    def _integrate_manual(
        self,
        x_m: float,
        y_m: float,
        yaw_rad: float,
        control: _ManualControl,
        delta_s: float,
    ) -> tuple[float, float, float]:
        angular = control.yaw_rate_rad_s
        linear = control.linear_m_s
        if abs(angular) < 1e-9:
            x_m += linear * delta_s * math.cos(yaw_rad)
            y_m += linear * delta_s * math.sin(yaw_rad)
        else:
            next_yaw = yaw_rad + angular * delta_s
            radius = linear / angular
            x_m += radius * (math.sin(next_yaw) - math.sin(yaw_rad))
            y_m -= radius * (math.cos(next_yaw) - math.cos(yaw_rad))
            yaw_rad = next_yaw
        bounds = self.world.bounds_m
        half_length = UNITREE_GO2_STANDING_LENGTH_M / 2.0
        half_width = UNITREE_GO2_STANDING_WIDTH_M / 2.0
        margin = max(half_length, half_width)
        x_m = min(bounds.x_max - margin, max(bounds.x_min + margin, x_m))
        y_m = min(bounds.y_max - margin, max(bounds.y_min + margin, y_m))
        return x_m, y_m, normalize_yaw(yaw_rad)

    def _build_segments(self) -> list[_Segment]:
        if self.config.type == "lawnmower":
            rect = self.config.rectangle_m
            y_values = list(
                np.arange(
                    rect.y_min,
                    rect.y_max + self.config.line_spacing_m * 0.5,
                    self.config.line_spacing_m,
                )
            )
            y_values = [min(float(y), rect.y_max) for y in y_values]
            if not y_values or y_values[-1] < rect.y_max:
                y_values.append(rect.y_max)
            points: list[tuple[float, float, float]] = []
            z = self.config.start_m[2]
            for index, y_value in enumerate(y_values):
                if index % 2 == 0:
                    points.extend([(rect.x_min, y_value, z), (rect.x_max, y_value, z)])
                else:
                    points.extend([(rect.x_max, y_value, z), (rect.x_min, y_value, z)])
            return self._segments_from_points(points)
        if self.config.type == "waypoints":
            points = [
                (waypoint.x_m, waypoint.y_m, waypoint.z_m) for waypoint in self.config.waypoints
            ]
            if not points:
                points = [self.config.start_m]
            return self._segments_from_points(points)
        return []

    def _segments_from_points(self, points: list[tuple[float, float, float]]) -> list[_Segment]:
        if len(points) < 2:
            return []
        segments: list[_Segment] = []
        cursor = 0.0
        for start, end in zip(points[:-1], points[1:], strict=True):
            distance = math.dist(start, end)
            travel = distance / self.config.speed_m_s if distance else 0.0
            segments.append(_Segment(cursor, cursor + travel, start, end))
            cursor += travel
            if self.config.dwell_at_waypoints_s > 0:
                segments.append(
                    _Segment(
                        cursor,
                        cursor + self.config.dwell_at_waypoints_s,
                        end,
                        end,
                    )
                )
                cursor += self.config.dwell_at_waypoints_s
        return segments

    def _segmented_pose(self, time_s: float) -> GroundTruthPose:
        if not self._segments:
            x, y, z = self.config.start_m
            return GroundTruthPose(x, y, z, self.config.yaw_start_rad)
        if self.config.loop and self._total_path_time_s > 0:
            time_s %= self._total_path_time_s
        if time_s >= self._segments[-1].end_s:
            x, y, z = self._segments[-1].end
            return GroundTruthPose(x, y, z, self._yaw_for_last_motion())
        segment = next(item for item in self._segments if item.end_s >= time_s)
        duration = segment.end_s - segment.start_s
        fraction = 1.0 if duration <= 0 else (time_s - segment.start_s) / duration
        x = segment.start[0] + fraction * (segment.end[0] - segment.start[0])
        y = segment.start[1] + fraction * (segment.end[1] - segment.start[1])
        z = segment.start[2] + fraction * (segment.end[2] - segment.start[2])
        dx = segment.end[0] - segment.start[0]
        dy = segment.end[1] - segment.start[1]
        if abs(dx) + abs(dy) < 1e-12:
            yaw = self._yaw_before(segment)
            return GroundTruthPose(x, y, z, yaw)
        yaw = math.atan2(dy, dx)
        speed = self.config.speed_m_s
        return GroundTruthPose(x, y, z, yaw, speed * math.cos(yaw), speed * math.sin(yaw))

    def _yaw_before(self, target: _Segment) -> float:
        index = self._segments.index(target)
        for segment in reversed(self._segments[:index]):
            dx = segment.end[0] - segment.start[0]
            dy = segment.end[1] - segment.start[1]
            if abs(dx) + abs(dy) > 1e-12:
                return math.atan2(dy, dx)
        return self.config.yaw_start_rad

    def _yaw_for_last_motion(self) -> float:
        for segment in reversed(self._segments):
            dx = segment.end[0] - segment.start[0]
            dy = segment.end[1] - segment.start[1]
            if abs(dx) + abs(dy) > 1e-12:
                return math.atan2(dy, dx)
        return self.config.yaw_start_rad

    def _circle_pose(self, time_s: float) -> GroundTruthPose:
        cx, cy, cz = self.config.circle_center_m
        angular_speed = self.config.speed_m_s / self.config.circle_radius_m
        theta = angular_speed * time_s
        x = cx + self.config.circle_radius_m * math.cos(theta)
        y = cy + self.config.circle_radius_m * math.sin(theta)
        yaw = normalize_yaw(theta + math.pi / 2)
        return GroundTruthPose(
            x,
            y,
            cz,
            yaw,
            -self.config.speed_m_s * math.sin(theta),
            self.config.speed_m_s * math.cos(theta),
            0.0,
            angular_speed,
        )

    def _scripted_pose(self, time_s: float) -> GroundTruthPose:
        frames = self.config.scripted_keyframes
        if not frames:
            x, y, z = self.config.start_m
            return GroundTruthPose(x, y, z, self.config.yaw_start_rad)
        if time_s <= frames[0].time_s:
            first = frames[0]
            return GroundTruthPose(first.x_m, first.y_m, first.z_m, first.yaw_rad)
        if time_s >= frames[-1].time_s:
            last = frames[-1]
            return GroundTruthPose(last.x_m, last.y_m, last.z_m, last.yaw_rad)
        before, after = next(
            (a, b)
            for a, b in zip(frames[:-1], frames[1:], strict=True)
            if a.time_s <= time_s <= b.time_s
        )
        fraction = (time_s - before.time_s) / (after.time_s - before.time_s)
        yaw_delta = normalize_yaw(after.yaw_rad - before.yaw_rad)
        duration = after.time_s - before.time_s
        return GroundTruthPose(
            before.x_m + fraction * (after.x_m - before.x_m),
            before.y_m + fraction * (after.y_m - before.y_m),
            before.z_m + fraction * (after.z_m - before.z_m),
            normalize_yaw(before.yaw_rad + fraction * yaw_delta),
            (after.x_m - before.x_m) / duration,
            (after.y_m - before.y_m) / duration,
            (after.z_m - before.z_m) / duration,
            yaw_delta / duration,
        )

    def _build_random_walk(self) -> list[GroundTruthPose]:
        rng = np.random.Generator(np.random.PCG64(self.seed + 17))
        x, y, z = self.config.start_m
        points = [GroundTruthPose(x, y, z, self.config.yaw_start_rad)]
        step_s = self.config.random_walk_step_s
        step_distance = self.config.speed_m_s * step_s
        bounds = self.world.bounds_m
        for _ in range(int(self.duration_s / step_s) + 2):
            yaw = float(rng.uniform(-math.pi, math.pi))
            x = min(bounds.x_max, max(bounds.x_min, x + math.cos(yaw) * step_distance))
            y = min(bounds.y_max, max(bounds.y_min, y + math.sin(yaw) * step_distance))
            points.append(
                GroundTruthPose(
                    x,
                    y,
                    z,
                    yaw,
                    self.config.speed_m_s * math.cos(yaw),
                    self.config.speed_m_s * math.sin(yaw),
                )
            )
        return points

    def _random_walk_pose(self, time_s: float) -> GroundTruthPose:
        step_s = self.config.random_walk_step_s
        index = min(int(time_s // step_s), len(self._random_points) - 2)
        fraction = (time_s - index * step_s) / step_s
        before = self._random_points[index]
        after = self._random_points[index + 1]
        return GroundTruthPose(
            before.x_m + fraction * (after.x_m - before.x_m),
            before.y_m + fraction * (after.y_m - before.y_m),
            before.z_m,
            after.yaw_rad,
            after.vx_m_s,
            after.vy_m_s,
        )
