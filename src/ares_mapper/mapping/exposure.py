"""Mission exposure and cumulative-dose consistency without evidence duplication."""

from __future__ import annotations

from dataclasses import dataclass

from ares_mapper.domain.models import ExposureSummary, ObservationWindow, RadiationSample


@dataclass(frozen=True, slots=True)
class DoseAudit:
    state: str
    cumulative_delta_uSv: float | None = None
    path_integral_uSv: float | None = None
    closure_error_uSv: float | None = None
    recovered_rate_uSv_h: float | None = None
    recovered_start_ns: int | None = None
    recovered_end_ns: int | None = None
    reset: bool = False


@dataclass(frozen=True, slots=True)
class CumulativeGapRecovery:
    """Independent interval recoverable from cumulative dose after packet loss."""

    start_ns: int
    end_ns: int
    duration_s: float
    dose_uSv: float
    rate_uSv_h: float
    rate_uncertainty_uSv_h: float


def recover_cumulative_gap(
    previous: RadiationSample,
    current: RadiationSample,
    quantization_uSv: float,
) -> CumulativeGapRecovery | None:
    """Recover only the interval not represented by instantaneous samples.

    The current integration is subtracted from the cumulative increment.  This
    prevents ``D`` from duplicating the current ``DR``/count observation.
    """

    if previous.sensor_id != current.sensor_id:
        return None
    previous_end = previous.integration_end_time_ns or previous.effective_measurement_time_ns
    current_start = current.integration_start_time_ns or current.effective_measurement_time_ns
    if current_start <= previous_end:
        return None
    missing_duration_s = (current_start - previous_end) / 1_000_000_000.0
    expected_period_s = max(float(current.integration_time_s or 1.0), 1e-6)
    sequence_gap = current.sequence > previous.sequence + 1
    temporal_gap = missing_duration_s > 0.5 * expected_period_s
    if not sequence_gap and not temporal_gap:
        return None
    cumulative_delta = current.cumulative_dose_uSv - previous.cumulative_dose_uSv
    quantum = max(0.0, quantization_uSv)
    if cumulative_delta < -quantum / 2.0:
        return None
    current_dose = (
        current.dose_rate_uSv_h * max(float(current.integration_time_s or 1.0), 1e-6) / 3600.0
    )
    recovered_dose = cumulative_delta - current_dose
    if recovered_dose < max(quantum / 2.0, 1e-12):
        return None
    rate = recovered_dose * 3600.0 / missing_duration_s
    quantization_std = quantum / (6.0**0.5) if quantum > 0 else max(1e-9, 0.05 * recovered_dose)
    rate_uncertainty = quantization_std * 3600.0 / missing_duration_s
    return CumulativeGapRecovery(
        start_ns=previous_end,
        end_ns=current_start,
        duration_s=missing_duration_s,
        dose_uSv=recovered_dose,
        rate_uSv_h=max(0.0, rate),
        rate_uncertainty_uSv_h=max(1e-9, rate_uncertainty),
    )


class MissionExposureTracker:
    def __init__(self, quantization_uSv: float = 0.01, threshold_uSv_h: float = 1.0) -> None:
        self.quantization_uSv = quantization_uSv
        self.threshold_uSv_h = threshold_uSv_h
        self._summary = ExposureSummary()
        self._previous: RadiationSample | None = None

    @property
    def summary(self) -> ExposureSummary:
        return self._summary.model_copy(deep=True)

    def update(self, window: ObservationWindow) -> DoseAudit:
        sample = window.radiation_sample
        path_dose = sample.dose_rate_uSv_h * window.integration_time_s / 3600.0
        self._summary.cumulative_robot_path_dose_uSv += path_dose
        self._summary.cumulative_detector_dose_uSv += path_dose
        self._summary.reported_cumulative_dose_uSv = sample.cumulative_dose_uSv
        if sample.dose_rate_uSv_h >= self.threshold_uSv_h:
            self._summary.time_above_threshold_s += window.integration_time_s
        previous = self._previous
        self._previous = sample
        if previous is None:
            self._summary.audit_state = "BASELINE"
            return DoseAudit("BASELINE", path_integral_uSv=path_dose)
        cumulative_delta = sample.cumulative_dose_uSv - previous.cumulative_dose_uSv
        if cumulative_delta < -self.quantization_uSv / 2.0:
            self._summary.reset_count += 1
            self._summary.audit_state = "RESET"
            return DoseAudit("RESET", cumulative_delta_uSv=cumulative_delta, reset=True)
        elapsed_ns = (sample.integration_end_time_ns or sample.effective_measurement_time_ns) - (
            previous.integration_end_time_ns or previous.effective_measurement_time_ns
        )
        elapsed_s = elapsed_ns / 1_000_000_000.0
        expected_interval_s = max(window.integration_time_s, 1e-6)
        gap = sample.sequence > previous.sequence + 1 or elapsed_s > 1.5 * expected_interval_s
        closure = cumulative_delta - path_dose
        self._summary.cumulative_closure_error_uSv += closure
        if (
            gap
            and elapsed_s > window.integration_time_s
            and cumulative_delta >= self.quantization_uSv
        ):
            missing_s = elapsed_s - window.integration_time_s
            recovered_dose = max(0.0, cumulative_delta - path_dose)
            if recovered_dose >= self.quantization_uSv / 2.0:
                self._summary.recovered_gap_count += 1
                self._summary.audit_state = "GAP_RECOVERABLE"
                end_ns = window.integration_start_ns
                start_ns = end_ns - int(missing_s * 1_000_000_000)
                return DoseAudit(
                    "GAP_RECOVERABLE",
                    cumulative_delta_uSv=cumulative_delta,
                    path_integral_uSv=path_dose,
                    closure_error_uSv=closure,
                    recovered_rate_uSv_h=recovered_dose * 3600.0 / missing_s,
                    recovered_start_ns=start_ns,
                    recovered_end_ns=end_ns,
                )
        self._summary.audit_state = "CONSISTENT"
        return DoseAudit(
            "CONSISTENT",
            cumulative_delta_uSv=cumulative_delta,
            path_integral_uSv=path_dose,
            closure_error_uSv=closure,
        )
