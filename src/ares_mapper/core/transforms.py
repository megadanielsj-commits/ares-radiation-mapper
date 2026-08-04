"""Quaternion interpolation and base-to-sensor transforms."""

from __future__ import annotations

import math

import numpy as np

from ares_mapper.config import SensorTransformConfig
from ares_mapper.domain.validation import normalize_yaw


def yaw_to_quaternion(yaw_rad: float) -> tuple[float, float, float, float]:
    half = yaw_rad / 2.0
    return (0.0, 0.0, math.sin(half), math.cos(half))


def quaternion_to_yaw(qx: float, qy: float, qz: float, qw: float) -> float:
    siny = 2.0 * (qw * qz + qx * qy)
    cosy = 1.0 - 2.0 * (qy * qy + qz * qz)
    return normalize_yaw(math.atan2(siny, cosy))


def slerp(
    q0: tuple[float, float, float, float],
    q1: tuple[float, float, float, float],
    fraction: float,
) -> tuple[float, float, float, float]:
    first = np.asarray(q0, dtype=float)
    second = np.asarray(q1, dtype=float)
    first /= np.linalg.norm(first)
    second /= np.linalg.norm(second)
    dot = float(np.dot(first, second))
    if dot < 0.0:
        second = -second
        dot = -dot
    dot = min(1.0, max(-1.0, dot))
    if dot > 0.9995:
        result = first + fraction * (second - first)
        result /= np.linalg.norm(result)
    else:
        theta_0 = math.acos(dot)
        theta = theta_0 * fraction
        tangent = second - first * dot
        tangent /= np.linalg.norm(tangent)
        result = first * math.cos(theta) + tangent * math.sin(theta)
    return tuple(float(value) for value in result)  # type: ignore[return-value]


def apply_sensor_transform(
    base_x_m: float,
    base_y_m: float,
    base_z_m: float,
    base_yaw_rad: float,
    transform: SensorTransformConfig,
) -> tuple[float, float, float, float]:
    dx, dy, dz = transform.translation_m
    sensor_x = base_x_m + math.cos(base_yaw_rad) * dx - math.sin(base_yaw_rad) * dy
    sensor_y = base_y_m + math.sin(base_yaw_rad) * dx + math.cos(base_yaw_rad) * dy
    sensor_z = base_z_m + dz
    sensor_yaw = normalize_yaw(base_yaw_rad + transform.rpy_rad[2])
    return sensor_x, sensor_y, sensor_z, sensor_yaw
