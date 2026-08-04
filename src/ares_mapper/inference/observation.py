"""Physically structured likelihoods for integrated radiological observations."""

from __future__ import annotations

import math

import numpy as np
from scipy.special import gammaln

from ares_mapper.config import DetectorConfig
from ares_mapper.domain.enums import EvidenceKind, ObservationMode
from ares_mapper.domain.models import ObservationWindow


class RadiationObservationModel:
    """Evaluates H1 and H0 using exactly one evidence channel per window."""

    def __init__(
        self,
        detectors: dict[str, DetectorConfig],
        *,
        source_z_m: float = 0.0,
        minimum_distance_m: float = 0.25,
    ) -> None:
        self.detectors = detectors
        self.source_z_m = source_z_m
        self.minimum_distance_m = minimum_distance_m

    def expected_rate(
        self,
        particles: np.ndarray,
        window: ObservationWindow,
    ) -> np.ndarray:
        """Return the path-averaged rate for H1 particles.

        Particles are ``x, y, log(q_1m), log(background)``.
        """

        path = np.asarray(
            [(point.x_m, point.y_m, point.z_m) for point in window.detector_path],
            dtype=float,
        )
        weights = np.asarray(window.path_time_weights_s, dtype=float)
        weights /= max(float(np.sum(weights)), 1e-12)
        dx = particles[:, 0, None] - path[None, :, 0]
        dy = particles[:, 1, None] - path[None, :, 1]
        dz = self.source_z_m - path[None, :, 2]
        distance_sq = np.maximum(
            dx * dx + dy * dy + dz * dz,
            self.minimum_distance_m**2,
        )
        strength = np.exp(particles[:, 2])[:, None]
        background = np.exp(particles[:, 3])[:, None]
        rates = background + strength / distance_sq
        return np.sum(rates * weights[None, :], axis=1)

    @staticmethod
    def expected_background(log_background: np.ndarray) -> np.ndarray:
        return np.exp(log_background)

    def log_likelihood_h1(self, particles: np.ndarray, window: ObservationWindow) -> np.ndarray:
        expected_rate = self.expected_rate(particles, window)
        pose_rate_std = self._pose_rate_uncertainty(particles, window)
        return self._log_likelihood(expected_rate, window, pose_rate_std)

    def log_likelihood_h0(
        self, log_background: np.ndarray, window: ObservationWindow
    ) -> np.ndarray:
        expected_rate = self.expected_background(log_background)
        return self._log_likelihood(expected_rate, window)

    def observed_rate(self, window: ObservationWindow) -> float:
        sample = window.radiation_sample
        detector = self.detectors[window.sensor_id]
        if window.observation_mode in {
            ObservationMode.COUNTS_POISSON,
            ObservationMode.COUNTS_NEGATIVE_BINOMIAL,
        }:
            if sample.cps is None:
                raise ValueError("count observation requires CPS")
            sensitivity = float(detector.sensitivity_cps_per_uSv_h or 0.0)
            if sensitivity <= 0:
                raise ValueError("count observation requires calibrated sensitivity")
            return sample.cps / sensitivity
        return sample.dose_rate_uSv_h

    def standardized_residual(self, expected_rate: float, window: ObservationWindow) -> float:
        detector = self.detectors[window.sensor_id]
        observed = self.observed_rate(window)
        scale = self._robust_scale(np.asarray([max(expected_rate, 0.0)]), window, detector)[0]
        return float((observed - expected_rate) / max(scale, 1e-9))

    def _log_likelihood(
        self,
        expected_rate: np.ndarray,
        window: ObservationWindow,
        additional_std: np.ndarray | None = None,
    ) -> np.ndarray:
        detector = self.detectors[window.sensor_id]
        mode = window.observation_mode
        if mode == ObservationMode.DOSE_RATE_ROBUST:
            observed = window.radiation_sample.dose_rate_uSv_h
            scale = self._robust_scale(expected_rate, window, detector)
            if additional_std is not None:
                scale = np.sqrt(scale * scale + additional_std * additional_std)
            degrees = max(2.01, detector.robust_degrees_of_freedom)
            standardized_sq = ((observed - expected_rate) / scale) ** 2
            return (
                gammaln((degrees + 1.0) / 2.0)
                - gammaln(degrees / 2.0)
                - 0.5 * math.log(degrees * math.pi)
                - np.log(scale)
                - ((degrees + 1.0) / 2.0) * np.log1p(standardized_sq / degrees)
            )

        sample = window.radiation_sample
        if sample.cps is None:
            return np.full_like(expected_rate, -np.inf)
        sensitivity = float(detector.sensitivity_cps_per_uSv_h or 0.0)
        observed_count = max(
            0,
            int(round(sample.cps * max(window.integration_time_s, 1e-9))),
        )
        mean_count = np.maximum(
            expected_rate * sensitivity * window.integration_time_s,
            1e-12,
        )
        if mode == ObservationMode.COUNTS_POISSON:
            return observed_count * np.log(mean_count) - mean_count - gammaln(observed_count + 1.0)
        dispersion = max(float(detector.overdispersion or 1.0), 1e-6)
        probability = dispersion / (dispersion + mean_count)
        return (
            gammaln(observed_count + dispersion)
            - gammaln(dispersion)
            - gammaln(observed_count + 1.0)
            + dispersion * np.log(probability)
            + observed_count * np.log1p(-probability)
        )

    @staticmethod
    def _robust_scale(
        expected_rate: np.ndarray,
        window: ObservationWindow,
        detector: DetectorConfig,
    ) -> np.ndarray:
        timing_fraction = min(1.0, window.sync_error_ms / 1000.0)
        relative = (
            detector.robust_fractional_std
            + detector.calibration_uncertainty_fraction
            + 0.10 * timing_fraction
        )
        scale = np.maximum(
            detector.robust_base_std_uSv_h + relative * expected_rate,
            1e-6,
        )
        if window.evidence_kind == EvidenceKind.CUMULATIVE_RECOVERY:
            quantization_rate_std = (
                detector.cumulative_quantization_uSv
                / math.sqrt(6.0)
                * 3600.0
                / max(window.integration_time_s, 1e-6)
            )
            scale = np.sqrt(scale * scale + quantization_rate_std**2 + (0.10 * expected_rate) ** 2)
        return scale

    def _pose_rate_uncertainty(
        self,
        particles: np.ndarray,
        window: ObservationWindow,
    ) -> np.ndarray:
        detector = self.detectors[window.sensor_id]
        path = np.asarray(
            [(point.x_m, point.y_m, point.z_m) for point in window.detector_path],
            dtype=float,
        )
        weights = np.asarray(window.path_time_weights_s, dtype=float)
        weights /= max(float(np.sum(weights)), 1e-12)
        dx = particles[:, 0, None] - path[None, :, 0]
        dy = particles[:, 1, None] - path[None, :, 1]
        dz = self.source_z_m - path[None, :, 2]
        distance_sq = np.maximum(
            dx * dx + dy * dy + dz * dz,
            self.minimum_distance_m**2,
        )
        strength = np.exp(particles[:, 2])[:, None]
        gradient_x = np.sum(
            2.0 * strength * dx / (distance_sq * distance_sq) * weights[None, :],
            axis=1,
        )
        gradient_y = np.sum(
            2.0 * strength * dy / (distance_sq * distance_sq) * weights[None, :],
            axis=1,
        )
        pose_std = max(
            (point.position_std_m for point in window.detector_path),
            default=0.0,
        )
        path_distance = float(np.sum(np.linalg.norm(np.diff(path[:, :2], axis=0), axis=1)))
        speed_m_s = path_distance / max(window.integration_time_s, 1e-9)
        timing_position_std = speed_m_s * window.sync_error_ms / 1000.0
        lever_arm_m = math.hypot(
            detector.transform_base_sensor.translation_m[0],
            detector.transform_base_sensor.translation_m[1],
        )
        extrinsic_std = math.hypot(
            detector.extrinsic_position_std_m,
            lever_arm_m * detector.extrinsic_yaw_std_rad,
        )
        response_position_std = (
            speed_m_s * window.response_time_std_s * detector.response_uncertainty_scale
        )
        combined_position_std = math.sqrt(
            pose_std * pose_std
            + timing_position_std * timing_position_std
            + extrinsic_std * extrinsic_std
            + response_position_std * response_position_std
        )
        return np.hypot(gradient_x, gradient_y) * combined_position_std
