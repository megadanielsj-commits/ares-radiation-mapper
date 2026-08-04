"""Typed, serialisable data contracts for every pipeline boundary."""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ares_mapper.domain.enums import (
    EvidenceKind,
    HealthState,
    IdentifiabilityState,
    MappingQuality,
    ObservationMode,
    Quality,
    SyncMethod,
)


class ContractModel(BaseModel):
    """Base class with strict assignment validation and JSON-friendly enums."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid", use_enum_values=False)


class RunContext(ContractModel):
    mission_id: str
    mode: str
    time_domain_id: str
    seed: int
    started_utc_ns: int


class PoseSample(ContractModel):
    schema_version: str = "1.0"
    mission_id: str
    source_id: str
    sequence: int
    time_domain_id: str
    timeline_time_ns: int
    source_time_ns: int | None = None
    received_utc_ns: int
    received_monotonic_ns: int
    time_uncertainty_ns: int = 0
    frame_id: str = "world"
    child_frame_id: str = "base"
    x_m: float
    y_m: float
    z_m: float
    qx: float = 0.0
    qy: float = 0.0
    qz: float = 0.0
    qw: float = 1.0
    roll_rad: float = 0.0
    pitch_rad: float = 0.0
    yaw_rad: float = 0.0
    vx_m_s: float = 0.0
    vy_m_s: float = 0.0
    vz_m_s: float = 0.0
    yaw_rate_rad_s: float = 0.0
    position_std_m: float | None = None
    yaw_std_rad: float | None = None
    position_covariance: tuple[float, ...] = ()
    orientation_covariance: tuple[float, ...] = ()
    quality: Quality = Quality.VALID
    is_ground_truth: bool = False
    truth_x_m: float | None = None
    truth_y_m: float | None = None
    truth_z_m: float | None = None
    truth_yaw_rad: float | None = None
    error_code: int = 0
    sport_mode: int = 1
    progress: float = 0.0
    gait_type: int = 0
    foot_raise_height_m: float = 0.0
    body_height_m: float = 0.32
    range_obstacle_m: tuple[float, float, float, float] = (5.0, 5.0, 5.0, 5.0)
    foot_force_raw: tuple[int, int, int, int] = (0, 0, 0, 0)
    foot_position_body_m: tuple[float, ...] = ()
    foot_speed_body_m_s: tuple[float, ...] = ()
    imu_gyroscope_rad_s: tuple[float, float, float] = (0.0, 0.0, 0.0)
    imu_accelerometer_m_s2: tuple[float, float, float] = (0.0, 0.0, 9.81)
    imu_temperature_c: int = 35
    raw_payload: dict[str, Any] | str | None = None

    @field_validator("qx", "qy", "qz", "qw", "x_m", "y_m", "z_m", "yaw_rad")
    @classmethod
    def finite_values(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("pose values must be finite")
        return value


class RadiationSample(ContractModel):
    schema_version: str = "1.0"
    mission_id: str
    sensor_id: str
    sequence: int
    time_domain_id: str
    timeline_time_ns: int
    source_time_ns: int | None = None
    received_utc_ns: int
    received_monotonic_ns: int
    time_uncertainty_ns: int = 0
    effective_measurement_time_ns: int
    dose_rate_uSv_h: float
    cumulative_dose_uSv: float = 0.0
    cps: int | None = None
    cpm: int | None = None
    average_dose_rate_uSv_h: float | None = None
    timer_s: int | None = None
    timed_dose_uSv: float | None = None
    integration_time_s: float | None = None
    integration_start_time_ns: int | None = None
    integration_end_time_ns: int | None = None
    latency_estimate_ms: float = 0.0
    time_uncertainty_ms: float = 0.0
    quality: Quality = Quality.VALID
    calibration_id: str | None = None
    alarm: bool = False
    raw_payload: str | None = None
    is_duplicate: bool = False
    true_dose_rate_uSv_h: float | None = None
    true_sensor_x_m: float | None = None
    true_sensor_y_m: float | None = None
    true_sensor_z_m: float | None = None

    @field_validator("dose_rate_uSv_h", "cumulative_dose_uSv")
    @classmethod
    def non_negative_finite(cls, value: float) -> float:
        if not math.isfinite(value) or value < 0:
            raise ValueError("radiological values must be finite and non-negative")
        return value


class DetectorPathPoint(ContractModel):
    """Observed detector pose used by quadrature; never contains simulation truth."""

    timeline_time_ns: int
    x_m: float
    y_m: float
    z_m: float
    yaw_rad: float = 0.0
    speed_m_s: float = 0.0
    position_std_m: float = 0.0
    time_uncertainty_ns: int = 0
    pose_sequence_before: int | None = None
    pose_sequence_after: int | None = None


class ObservationWindow(ContractModel):
    """One statistically independent detector integration window."""

    schema_version: str = "1.1"
    mission_id: str
    sensor_id: str
    observation_sequence: int
    radiation_sample: RadiationSample
    detector_path: list[DetectorPathPoint]
    path_time_weights_s: list[float]
    pose_covariances: list[tuple[float, ...]] = Field(default_factory=list)
    extrinsic_transform: dict[str, tuple[float, ...]] = Field(default_factory=dict)
    integration_start_ns: int
    integration_end_ns: int
    integration_time_s: float
    maximum_pose_gap_ms: float
    sync_error_ms: float
    response_delay_s: float = 0.0
    response_time_std_s: float = 0.0
    observation_mode: ObservationMode = ObservationMode.DOSE_RATE_ROBUST
    evidence_kind: EvidenceKind = EvidenceKind.INSTANTANEOUS
    quality_flags: list[str] = Field(default_factory=list)
    quality: Quality = Quality.VALID

    @model_validator(mode="after")
    def path_and_weights_match(self) -> ObservationWindow:
        if not self.detector_path:
            raise ValueError("observation window requires a detector path")
        if len(self.detector_path) != len(self.path_time_weights_s):
            raise ValueError("detector path and quadrature weights must have equal length")
        if any(weight < 0 or not math.isfinite(weight) for weight in self.path_time_weights_s):
            raise ValueError("path time weights must be finite and non-negative")
        if self.integration_time_s <= 0:
            raise ValueError("integration time must be positive")
        if self.response_delay_s < 0 or self.response_time_std_s < 0:
            raise ValueError("detector response timing terms must be non-negative")
        return self

    @property
    def representative_xyz(self) -> tuple[float, float, float]:
        weights = self.path_time_weights_s
        total = max(sum(weights), 1e-12)
        path_with_weights = zip(self.detector_path, weights, strict=True)
        weighted = [
            (point.x_m * weight, point.y_m * weight, point.z_m * weight)
            for point, weight in path_with_weights
        ]
        return (
            sum(item[0] for item in weighted) / total,
            sum(item[1] for item in weighted) / total,
            sum(item[2] for item in weighted) / total,
        )


class MappedSample(ContractModel):
    schema_version: str = "1.0"
    mission_id: str
    mapped_sequence: int
    radiation_sequence: int
    sensor_id: str
    time_domain_id: str
    pose_before_sequence: int | None = None
    pose_after_sequence: int | None = None
    effective_measurement_time_ns: int
    frame_id: str
    base_x_m: float
    base_y_m: float
    base_z_m: float
    sensor_x_m: float
    sensor_y_m: float
    sensor_z_m: float
    sensor_yaw_rad: float
    dose_rate_uSv_h_raw: float
    dose_rate_uSv_h_filtered: float
    cumulative_dose_uSv: float = 0.0
    cps: int | None = None
    cpm: int | None = None
    average_dose_rate_uSv_h: float | None = None
    timer_s: int | None = None
    timed_dose_uSv: float | None = None
    integration_time_s: float | None = None
    integration_start_time_ns: int | None = None
    integration_end_time_ns: int | None = None
    path_length_m: float = 0.0
    mean_speed_m_s: float = 0.0
    dwell_time_s: float = 0.0
    position_std_m: float | None = None
    yaw_std_rad: float | None = None
    base_vx_m_s: float = 0.0
    base_vy_m_s: float = 0.0
    base_yaw_rate_rad_s: float = 0.0
    alarm: bool = False
    sync_method: SyncMethod
    max_pose_gap_ms: float
    sync_error_estimate_ms: float
    pose_quality: Quality
    radiation_quality: Quality
    mapping_quality: MappingQuality
    flags: list[str] = Field(default_factory=list)
    true_dose_rate_uSv_h: float | None = None
    true_sensor_x_m: float | None = None
    true_sensor_y_m: float | None = None
    true_sensor_z_m: float | None = None


class ScenarioEvent(ContractModel):
    schema_version: str = "1.0"
    mission_id: str
    simulation_time_ns: int
    received_utc_ns: int
    event_type: str
    target_id: str
    old_value: Any = None
    new_value: Any = None
    actor: str = "operator"


class CredibleRegion(ContractModel):
    probability: float
    center_x_m: float
    center_y_m: float
    conservative_radius_m: float
    area_m2: float
    cells: list[tuple[float, float, float, float]] = Field(default_factory=list)


class SourcePosterior(ContractModel):
    schema_version: str = "1.1"
    mission_id: str
    update_sequence: int
    map_time_ns: int
    particle_count: int
    particles: list[tuple[float, float, float, float]] = Field(default_factory=list)
    log_weights: list[float] = Field(default_factory=list)
    p_source_exists: float
    posterior_mean_x_y: tuple[float, float]
    posterior_map_x_y: tuple[float, float]
    posterior_median_strength_at_1m: float
    posterior_strength_interval_90: tuple[float, float]
    posterior_background: float
    posterior_background_interval_90: tuple[float, float]
    credible_regions: dict[str, CredibleRegion]
    entropy: float
    effective_sample_size: float
    identifiability_state: IdentifiabilityState
    detected: bool = False
    model_diagnostics: dict[str, float | int | str | bool | None] = Field(default_factory=dict)


class FieldCell(ContractModel):
    schema_version: str = "1.1"
    bounds: tuple[float, float, float, float]
    level: int
    center: tuple[float, float]
    posterior_mean: float
    posterior_quantiles: tuple[float, float, float]
    posterior_std: float
    residual_mean: float
    residual_variance: float
    mean_uSv_h: float
    p05_uSv_h: float
    p50_uSv_h: float
    p95_uSv_h: float
    relative_uncertainty: float
    probability_above_threshold: float
    coverage_time_s: float
    effective_observations: float
    distance_to_support_m: float | None
    last_update_ns: int | None
    refinement_reason: list[str] = Field(default_factory=list)
    model_fraction: float = 1.0
    residual_fraction: float = 0.0


class ExposureSummary(ContractModel):
    schema_version: str = "1.1"
    cumulative_detector_dose_uSv: float = 0.0
    cumulative_robot_path_dose_uSv: float = 0.0
    reported_cumulative_dose_uSv: float = 0.0
    cumulative_closure_error_uSv: float = 0.0
    time_above_threshold_s: float = 0.0
    recovered_gap_count: int = 0
    reset_count: int = 0
    audit_state: str = "NO_DATA"


class MapPrediction(ContractModel):
    schema_version: str = "1.1"
    mission_id: str
    frame_id: str
    map_time_ns: int
    temporal_mode: str
    time_window_start_ns: int | None
    time_window_end_ns: int
    value_name: str = "dose_rate_uSv_h"
    unit: str = "uSv/h"
    x_coordinates_m: list[float]
    y_coordinates_m: list[float]
    values_row_major: list[float | None]
    coverage_mask_row_major: list[bool]
    p05_values_row_major: list[float | None] = Field(default_factory=list)
    p50_values_row_major: list[float | None] = Field(default_factory=list)
    p95_values_row_major: list[float | None] = Field(default_factory=list)
    uncertainty_values_row_major: list[float | None] = Field(default_factory=list)
    relative_uncertainty_row_major: list[float | None] = Field(default_factory=list)
    coverage_time_row_major: list[float | None] = Field(default_factory=list)
    exposure_values_row_major: list[float | None] = Field(default_factory=list)
    source_probability_row_major: list[float | None] = Field(default_factory=list)
    probability_above_threshold_row_major: list[float | None] = Field(default_factory=list)
    distance_to_support_row_major: list[float | None] = Field(default_factory=list)
    model_fraction_row_major: list[float | None] = Field(default_factory=list)
    residual_fraction_row_major: list[float | None] = Field(default_factory=list)
    truth_values_row_major: list[float | None] | None = None
    grid_shape: tuple[int, int]
    sample_count: int
    interpolator: str = "idw"
    parameters: dict[str, Any] = Field(default_factory=dict)
    hotspot: dict[str, Any] | None = None
    source_estimate: dict[str, Any] | None = None
    source_posterior: SourcePosterior | None = None
    adaptive_cells: list[FieldCell] = Field(default_factory=list)
    exposure: ExposureSummary | None = None
    layers: list[str] = Field(default_factory=list)
    metrics: dict[str, float | int | str | bool | None] = Field(default_factory=dict)


class SourceHealth(ContractModel):
    schema_version: str = "1.0"
    source_id: str
    state: HealthState = HealthState.STARTING
    last_sample_timeline_time_ns: int | None = None
    last_receive_utc_ns: int | None = None
    observed_rate_hz: float = 0.0
    stale_for_ms: float | None = None
    received_count: int = 0
    invalid_count: int = 0
    dropped_count: int = 0
    reconnect_count: int = 0
    last_error_code: str | None = None
    last_error_message: str | None = None


class TelemetrySnapshot(ContractModel):
    schema_version: str = "1.1"
    mission_id: str | None
    state: str
    simulation_time_ns: int
    simulation_speed: float
    pose: PoseSample | None = None
    radiation: RadiationSample | None = None
    mapped_sample: MappedSample | None = None
    sample_count: int = 0
    maximum_observed_uSv_h: float | None = None
    cumulative_dose_uSv: float | None = None
    source_posterior: SourcePosterior | None = None
    exposure: ExposureSummary | None = None
    map_metrics: dict[str, float | int | str | bool | None] = Field(default_factory=dict)
    alerts: list[str] = Field(default_factory=list)
