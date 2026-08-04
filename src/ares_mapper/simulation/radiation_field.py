"""Time-varying radiological ground-truth field."""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from ares_mapper.config import (
    PositionKeyframeConfig,
    RadiationSourceConfig,
    StrengthKeyframeConfig,
    WorldConfig,
)


def _interpolate_scalar(
    time_s: float,
    times: Sequence[float],
    values: Sequence[float],
    mode: str,
) -> float:
    if time_s >= times[-1]:
        return float(values[-1])
    if time_s <= times[0]:
        return float(values[0])
    index = int(np.searchsorted(times, time_s, side="right"))
    if mode == "step":
        return float(values[index - 1])
    fraction = (time_s - times[index - 1]) / (times[index] - times[index - 1])
    return float(values[index - 1] + fraction * (values[index] - values[index - 1]))


class RadiationField:
    def __init__(self, world: WorldConfig, sources: list[RadiationSourceConfig]) -> None:
        self.world = world
        self.sources = sources

    def source_position(
        self, source: RadiationSourceConfig, time_s: float
    ) -> tuple[float, float, float]:
        frames = source.position_keyframes
        times = [frame.time_s for frame in frames]
        return (
            _interpolate_scalar(
                time_s,
                times,
                [frame.x_m for frame in frames],
                source.keyframe_interpolation,
            ),
            _interpolate_scalar(
                time_s,
                times,
                [frame.y_m for frame in frames],
                source.keyframe_interpolation,
            ),
            _interpolate_scalar(
                time_s,
                times,
                [frame.z_m for frame in frames],
                source.keyframe_interpolation,
            ),
        )

    def source_strength(self, source: RadiationSourceConfig, time_s: float) -> float:
        frames = source.strength_keyframes
        return _interpolate_scalar(
            time_s,
            [frame.time_s for frame in frames],
            [frame.dose_rate_at_reference_uSv_h for frame in frames],
            source.keyframe_interpolation,
        )

    def dose_rate(self, x_m: float, y_m: float, z_m: float, time_s: float) -> float:
        total = max(0.0, self.world.background.dose_rate_uSv_h)
        for source in self.sources:
            if not source.enabled:
                continue
            sx, sy, sz = self.source_position(source, time_s)
            distance = math.dist((x_m, y_m, z_m), (sx, sy, sz))
            strength = max(0.0, self.source_strength(source, time_s))
            if source.model == "gaussian":
                contribution = strength * math.exp(
                    -(distance**2) / (2.0 * source.gaussian_sigma_m**2)
                )
            else:
                effective_distance = max(distance, source.minimum_distance_m)
                contribution = strength * (source.reference_distance_m / effective_distance) ** 2
            contribution *= self._transmission((x_m, y_m), (sx, sy))
            total += contribution
        return max(0.0, total)

    def grid(
        self,
        x_coordinates: np.ndarray,
        y_coordinates: np.ndarray,
        z_m: float,
        time_s: float,
    ) -> np.ndarray:
        xx, yy = np.meshgrid(x_coordinates, y_coordinates)
        values = np.full(xx.shape, self.world.background.dose_rate_uSv_h, dtype=float)
        for source in self.sources:
            if not source.enabled:
                continue
            sx, sy, sz = self.source_position(source, time_s)
            distance = np.sqrt((xx - sx) ** 2 + (yy - sy) ** 2 + (z_m - sz) ** 2)
            strength = max(0.0, self.source_strength(source, time_s))
            if source.model == "gaussian":
                values += strength * np.exp(-(distance**2) / (2.0 * source.gaussian_sigma_m**2))
            else:
                effective = np.maximum(distance, source.minimum_distance_m)
                values += strength * (source.reference_distance_m / effective) ** 2
        return np.maximum(values, 0.0)

    def update_source(
        self,
        source_id: str,
        time_s: float,
        *,
        x_m: float | None = None,
        y_m: float | None = None,
        z_m: float | None = None,
        strength_uSv_h: float | None = None,
        enabled: bool | None = None,
    ) -> dict[str, object]:
        source = next((item for item in self.sources if item.id == source_id), None)
        if source is None:
            raise KeyError(source_id)
        old = {
            "position_m": self.source_position(source, time_s),
            "strength_uSv_h": self.source_strength(source, time_s),
            "enabled": source.enabled,
        }
        current_x, current_y, current_z = self.source_position(source, time_s)
        if x_m is not None or y_m is not None or z_m is not None:
            source.position_keyframes.extend(
                (
                    PositionKeyframeConfig(
                        time_s=time_s,
                        x_m=current_x,
                        y_m=current_y,
                        z_m=current_z,
                    ),
                    PositionKeyframeConfig(
                        time_s=time_s,
                        x_m=current_x if x_m is None else x_m,
                        y_m=current_y if y_m is None else y_m,
                        z_m=current_z if z_m is None else z_m,
                    ),
                )
            )
            source.position_keyframes.sort(key=lambda frame: frame.time_s)
        if strength_uSv_h is not None:
            current_strength = self.source_strength(source, time_s)
            source.strength_keyframes.extend(
                (
                    StrengthKeyframeConfig(
                        time_s=time_s,
                        dose_rate_at_reference_uSv_h=current_strength,
                    ),
                    StrengthKeyframeConfig(
                        time_s=time_s,
                        dose_rate_at_reference_uSv_h=max(0.0, strength_uSv_h),
                    ),
                )
            )
            source.strength_keyframes.sort(key=lambda frame: frame.time_s)
        if enabled is not None:
            source.enabled = enabled
        return old

    def _transmission(
        self,
        detector_xy: tuple[float, float],
        source_xy: tuple[float, float],
    ) -> float:
        transmission = 1.0
        for obstacle in self.world.obstacles:
            polygon = obstacle.polygon_xy_m
            if any(
                _segments_intersect(
                    detector_xy,
                    source_xy,
                    polygon[index],
                    polygon[(index + 1) % len(polygon)],
                )
                for index in range(len(polygon))
            ):
                transmission *= obstacle.transmission
        return transmission


def _segments_intersect(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> bool:
    def orientation(
        p: tuple[float, float],
        q: tuple[float, float],
        r: tuple[float, float],
    ) -> float:
        return (q[1] - p[1]) * (r[0] - q[0]) - (q[0] - p[0]) * (r[1] - q[1])

    return (
        orientation(a, b, c) * orientation(a, b, d) < 0
        and orientation(c, d, a) * orientation(c, d, b) < 0
    )
