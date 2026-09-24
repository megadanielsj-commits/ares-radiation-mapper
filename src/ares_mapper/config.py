"""YAML configuration models and loading."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

MILLISIEVERT_TO_MICROSIEVERT = 1_000.0
PUBLIC_ANNUAL_EFFECTIVE_DOSE_LIMIT_MSV = 1.0
HOURS_PER_REFERENCE_YEAR = 365.0 * 24.0
PUBLIC_CONTINUOUS_REFERENCE_RATE_USV_H = (
    PUBLIC_ANNUAL_EFFECTIVE_DOSE_LIMIT_MSV * MILLISIEVERT_TO_MICROSIEVERT / HOURS_PER_REFERENCE_YEAR
)
IOE_REFERENCE_HOURS_PER_YEAR = 2_000.0
IOE_ANNUAL_RECORDING_LEVEL_MSV = 1.0
IOE_ANNUAL_INVESTIGATION_LEVEL_MSV = 6.0
IOE_ANNUAL_EFFECTIVE_DOSE_LIMIT_MSV = 20.0
IOE_MAXIMUM_SINGLE_YEAR_EFFECTIVE_DOSE_MSV = 50.0
IOE_RECORDING_EQUIVALENT_RATE_USV_H = (
    IOE_ANNUAL_RECORDING_LEVEL_MSV * MILLISIEVERT_TO_MICROSIEVERT / IOE_REFERENCE_HOURS_PER_YEAR
)
IOE_INVESTIGATION_EQUIVALENT_RATE_USV_H = (
    IOE_ANNUAL_INVESTIGATION_LEVEL_MSV * MILLISIEVERT_TO_MICROSIEVERT / IOE_REFERENCE_HOURS_PER_YEAR
)
IOE_LIMIT_EQUIVALENT_RATE_USV_H = (
    IOE_ANNUAL_EFFECTIVE_DOSE_LIMIT_MSV
    * MILLISIEVERT_TO_MICROSIEVERT
    / IOE_REFERENCE_HOURS_PER_YEAR
)
IOE_MAXIMUM_EQUIVALENT_RATE_USV_H = (
    IOE_MAXIMUM_SINGLE_YEAR_EFFECTIVE_DOSE_MSV
    * MILLISIEVERT_TO_MICROSIEVERT
    / IOE_REFERENCE_HOURS_PER_YEAR
)
DEFAULT_SIMULATION_SOURCE_STRENGTH_USV_H = 10_000.0
MAX_SIMULATION_SOURCE_STRENGTH_USV_H = 10_000_000.0
UNITREE_GO2_STANDING_LENGTH_M = 0.70
UNITREE_GO2_STANDING_WIDTH_M = 0.31
UNITREE_GO2_STANDING_HEIGHT_M = 0.40
UNITREE_GO2_CROUCHED_LENGTH_M = 0.76
UNITREE_GO2_CROUCHED_WIDTH_M = 0.31
UNITREE_GO2_CROUCHED_HEIGHT_M = 0.20


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ApplicationConfig(ConfigModel):
    name: str = "ARES Radiation Mapper"
    bind_host: str = "127.0.0.1"
    bind_port: int = 8000
    data_directory: Path = Path("data/missions")
    log_level: str = "INFO"
    open_browser: bool = True


class MissionConfig(ConfigModel):
    name: str = "ares-demo"
    mode: str = "sim"
    seed: int = 20260728
    duration_s: float = 120.0
    simulation_speed: float = 1.0

    @field_validator("duration_s", "simulation_speed")
    @classmethod
    def positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("value must be positive")
        return value


class BoundsConfig(ConfigModel):
    x_min: float = 0.0
    x_max: float = 10.0
    y_min: float = 0.0
    y_max: float = 8.0

    @model_validator(mode="after")
    def ordered(self) -> BoundsConfig:
        if self.x_max <= self.x_min or self.y_max <= self.y_min:
            raise ValueError("world bounds must have positive area")
        return self


class BackgroundConfig(ConfigModel):
    model: Literal["constant", "keyframes"] = "constant"
    dose_rate_uSv_h: float = 0.10
    keyframes: list[dict[str, float]] = Field(default_factory=list)


class ObstacleConfig(ConfigModel):
    id: str
    polygon_xy_m: list[tuple[float, float]]
    transmission: float = 1.0

    @field_validator("transmission")
    @classmethod
    def valid_transmission(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("transmission must be between zero and one")
        return value


class WorldConfig(ConfigModel):
    frame_id: str = "world"
    bounds_m: BoundsConfig = Field(default_factory=BoundsConfig)
    z_floor_m: float = 0.0
    map_resolution_m: float = 0.10
    background: BackgroundConfig = Field(default_factory=BackgroundConfig)
    obstacles: list[ObstacleConfig] = Field(default_factory=list)


class RectangleConfig(ConfigModel):
    x_min: float = 1.0
    x_max: float = 9.0
    y_min: float = 1.0
    y_max: float = 7.0


class PoseKeyframeConfig(ConfigModel):
    time_s: float
    x_m: float
    y_m: float
    z_m: float = 0.32
    yaw_rad: float = 0.0


class WaypointConfig(ConfigModel):
    x_m: float
    y_m: float
    z_m: float = 0.32
    speed_m_s: float | None = None
    dwell_s: float = 0.0


class TrajectoryConfig(ConfigModel):
    type: Literal[
        "waypoints", "lawnmower", "circle", "stationary", "random_walk", "manual", "scripted"
    ] = "lawnmower"
    start_m: tuple[float, float, float] = (1.0, 1.0, 0.32)
    yaw_start_rad: float = 0.0
    speed_m_s: float = 0.40
    line_spacing_m: float = 0.75
    rectangle_m: RectangleConfig = Field(default_factory=RectangleConfig)
    turn_duration_s: float = 1.5
    dwell_at_waypoints_s: float = 0.0
    loop: bool = False
    waypoints: list[WaypointConfig] = Field(default_factory=list)
    circle_center_m: tuple[float, float, float] = (5.0, 4.0, 0.32)
    circle_radius_m: float = 2.5
    random_walk_step_s: float = 1.0
    scripted_keyframes: list[PoseKeyframeConfig] = Field(default_factory=list)

    @field_validator("speed_m_s", "line_spacing_m", "circle_radius_m")
    @classmethod
    def positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("trajectory values must be positive")
        return value


class OdometryConfig(ConfigModel):
    publish_rate_hz: float = 20.0
    position_noise_std_m: float = 0.01
    yaw_noise_std_rad: float = 0.005
    drift_m_per_min: float = 0.02
    yaw_drift_rad_per_min: float = 0.005
    bias_x_m: float = 0.0
    bias_y_m: float = 0.0
    latency_ms: float = 20.0
    jitter_ms_std: float = 3.0
    dropout_probability: float = 0.0
    outlier_probability: float = 0.0
    outlier_position_std_m: float = 0.50

    @field_validator("publish_rate_hz")
    @classmethod
    def rate_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("publish rate must be positive")
        return value

    @field_validator("dropout_probability", "outlier_probability")
    @classmethod
    def probability(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("probability must be between zero and one")
        return value


class PoseProviderConfig(ConfigModel):
    """Selects the pose boundary without coupling inference to a provider."""

    provider: Literal[
        "manual_sim",
        "simulated",
        "unitree_sportmode",
        "ros_tf",
        "replay",
    ] = "manual_sim"
    network_interface: str = "enp3s0"
    domain_id: int = 0
    topic: str = "rt/sportmodestate"
    output_rate_hz: float = 20.0
    frame_id: str = "map"
    child_frame_id: str = "base_link"
    position_std_m: float = 0.10
    yaw_std_rad: float = 0.05

    @field_validator("position_std_m", "yaw_std_rad")
    @classmethod
    def non_negative(cls, value: float) -> float:
        if value < 0:
            raise ValueError("pose uncertainty cannot be negative")
        return value

    @field_validator("output_rate_hz")
    @classmethod
    def positive_output_rate(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("pose output rate must be positive")
        return value


class RobotConfig(ConfigModel):
    """Physical Go2 footprint plus presentation-only dashboard parameters."""

    model: Literal["unitree_go2"] = "unitree_go2"
    posture: Literal["standing", "crouched"] = "standing"
    length_m: float = UNITREE_GO2_STANDING_LENGTH_M
    width_m: float = UNITREE_GO2_STANDING_WIDTH_M
    height_m: float = UNITREE_GO2_STANDING_HEIGHT_M
    minimum_display_length_px: float = 30.0
    visual_smoothing_time_constant_s: float = 0.08

    @field_validator(
        "length_m",
        "width_m",
        "height_m",
        "minimum_display_length_px",
    )
    @classmethod
    def positive_geometry(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("robot geometry values must be positive")
        return value

    @field_validator("visual_smoothing_time_constant_s")
    @classmethod
    def non_negative_smoothing(cls, value: float) -> float:
        if value < 0:
            raise ValueError("visual smoothing time constant cannot be negative")
        return value


class PositionKeyframeConfig(ConfigModel):
    time_s: float
    x_m: float
    y_m: float
    z_m: float = 0.8


class StrengthKeyframeConfig(ConfigModel):
    time_s: float
    dose_rate_at_reference_uSv_h: float


class RadiationSourceConfig(ConfigModel):
    id: str
    model: Literal["inverse_square", "gaussian"] = "inverse_square"
    enabled: bool = True
    position_keyframes: list[PositionKeyframeConfig]
    strength_keyframes: list[StrengthKeyframeConfig]
    keyframe_interpolation: Literal["linear", "step"] = "linear"
    reference_distance_m: float = 1.0
    minimum_distance_m: float = 0.25
    gaussian_sigma_m: float = 1.0

    @model_validator(mode="after")
    def has_keyframes(self) -> RadiationSourceConfig:
        if not self.position_keyframes or not self.strength_keyframes:
            raise ValueError("radiation source requires position and strength keyframes")
        self.position_keyframes.sort(key=lambda item: item.time_s)
        self.strength_keyframes.sort(key=lambda item: item.time_s)
        return self


class SensorTransformConfig(ConfigModel):
    translation_m: tuple[float, float, float] = (0.0, 0.0, 0.25)
    rpy_rad: tuple[float, float, float] = (0.0, 0.0, 0.0)


class DetectorConfig(ConfigModel):
    sensor_id: str = "simulated_fs5000"
    source_type: str = "simulated"
    replay_csv_path: Path | None = None
    live_jsonl_path: Path | None = None
    serial_port: str = "auto"
    publish_rate_hz: float = 1.0
    transform_base_sensor: SensorTransformConfig = Field(default_factory=SensorTransformConfig)
    extrinsic_position_std_m: float = 0.02
    extrinsic_yaw_std_rad: float = 0.02
    response_mode: Literal["dose_direct", "counts_derived"] = "counts_derived"
    response_time_constant_s: float = 1.5
    response_compensation_enabled: bool = True
    response_uncertainty_scale: float = Field(default=1.0, ge=0.0, le=5.0)
    fixed_latency_ms: float = 300.0
    jitter_ms_std: float = 20.0
    dose_rate_quantization_uSv_h: float = 0.01
    cpm_per_uSv_h: float = 157.0
    sensitivity_cps_per_uSv_h: float | None = None
    observation_mode: Literal[
        "dose_rate_robust",
        "counts_poisson",
        "counts_negative_binomial",
    ] = "dose_rate_robust"
    overdispersion: float | None = None
    robust_degrees_of_freedom: float = 4.0
    robust_base_std_uSv_h: float = 0.03
    robust_fractional_std: float = 0.12
    calibration_id: str | None = None
    calibration_uncertainty_fraction: float = 0.10
    cumulative_quantization_uSv: float = 0.01
    additive_noise_std_uSv_h: float = 0.01
    multiplicative_noise_fraction: float = 0.03
    dropout_probability: float = 0.0
    duplicate_probability: float = 0.0
    outlier_probability: float = 0.0
    outlier_multiplier: float = 4.0
    alarm_threshold_uSv_h: float | None = None

    @field_validator("publish_rate_hz", "cpm_per_uSv_h")
    @classmethod
    def positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("detector value must be positive")
        return value

    @field_validator("extrinsic_position_std_m", "extrinsic_yaw_std_rad")
    @classmethod
    def non_negative_uncertainty(cls, value: float) -> float:
        if value < 0:
            raise ValueError("detector extrinsic uncertainty cannot be negative")
        return value

    @model_validator(mode="after")
    def validate_observation_mode(self) -> DetectorConfig:
        if self.sensitivity_cps_per_uSv_h is None:
            self.sensitivity_cps_per_uSv_h = self.cpm_per_uSv_h / 60.0
        if (
            self.observation_mode in {"counts_poisson", "counts_negative_binomial"}
            and self.sensitivity_cps_per_uSv_h <= 0
        ):
            raise ValueError("count modes require positive sensitivity")
        if self.observation_mode == "counts_negative_binomial" and (
            self.overdispersion is None or self.overdispersion <= 0
        ):
            raise ValueError("negative-binomial mode requires positive overdispersion")
        return self

    @model_validator(mode="after")
    def replay_requires_path(self) -> DetectorConfig:
        if self.source_type == "radiacode_jsonl" and self.live_jsonl_path is None:
            raise ValueError("radiacode_jsonl requires live_jsonl_path")
        if self.source_type == "csv_replay" and self.replay_csv_path is None:
            raise ValueError("csv_replay detector requires replay_csv_path")
        return self

    @field_validator("dropout_probability", "duplicate_probability", "outlier_probability")
    @classmethod
    def probability(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("probability must be between zero and one")
        return value


class SynchronizationConfig(ConfigModel):
    timebase: str = "timeline"
    holdback_ms: float = 100.0
    max_pose_gap_ms: float = 500.0
    radiation_latency_ms: float = 300.0
    radiation_time_uncertainty_ms: float = 500.0
    strategy: str = "linear_slerp"
    allow_nearest_fallback: bool = True
    nearest_fallback_max_ms: float = 250.0


class FilterConfig(ConfigModel):
    type: Literal["none", "ema", "median"] = "none"
    alpha: float = 0.35
    window: int = 5


class MappingConfig(ConfigModel):
    value: str = "dose_rate_uSv_h"
    interpolator: Literal["idw", "gaussian", "hybrid", "probabilistic"] = "probabilistic"
    grid_resolution_m: float = 0.25
    idw_power: float = 2.0
    epsilon_m: float = 0.02
    influence_radius_m: float = 0.75
    minimum_neighbors: int = 1
    maximum_neighbors: int = 50
    coverage_mode: Literal["radius", "radius_and_convex_hull"] = "radius_and_convex_hull"
    temporal_mode: Literal["cumulative", "sliding_window", "time_slice", "time_decay"] = (
        "cumulative"
    )
    sliding_window_s: float = 30.0
    time_decay_tau_s: float = 15.0
    refresh_rate_hz: float = 2.0
    source_localization_min_samples: int = 6
    global_model_stable_updates: int = Field(default=5, ge=1, le=100)
    global_model_transition_updates: int = Field(default=6, ge=1, le=100)
    global_model_unstable_grace_updates: int = Field(default=2, ge=0, le=100)
    global_model_smoothing_alpha: float = Field(default=0.45, gt=0.0, le=1.0)
    source_reference_distance_m: float = 1.0
    source_minimum_distance_m: float = 0.25
    filter: FilterConfig = Field(default_factory=FilterConfig)


class InferenceConfig(ConfigModel):
    model: Literal["single_source_particle_filter"] = "single_source_particle_filter"
    particles: int = 2048
    render_particles: int = 256
    resample_ess_fraction: float = 0.50
    rejuvenation: Literal["liu_west", "none"] = "liu_west"
    liu_west_h: float = 0.10
    prior_refresh_fraction: float = 0.02
    source_exists_prior: float = 0.50
    source_exists_threshold: float = 0.95
    source_strength_min_uSv_h: float = 0.01
    source_strength_max_uSv_h: float = 10_000.0
    source_z_m: float = 0.0
    source_detection_floor_uSv_h: float = 0.03
    background_prior_uSv_h: float | None = None
    background_prior_std_uSv_h: float = 0.05
    background_min_uSv_h: float = 0.001
    background_max_uSv_h: float = 10.0
    minimum_independent_cells: int = 6
    minimum_spatial_span_m: float = 1.0
    stable_radius_95_m: float = 1.0
    mismatch_normalized_rmse: float = 3.0

    @field_validator("particles", "render_particles", "minimum_independent_cells")
    @classmethod
    def positive_integer(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("inference counts must be positive")
        return value

    @field_validator(
        "resample_ess_fraction",
        "liu_west_h",
        "prior_refresh_fraction",
        "source_exists_prior",
        "source_exists_threshold",
    )
    @classmethod
    def unit_interval(cls, value: float) -> float:
        if not 0.0 < value <= 1.0:
            raise ValueError("value must be in (0, 1]")
        return value

    @model_validator(mode="after")
    def ordered_limits(self) -> InferenceConfig:
        if self.render_particles > self.particles:
            raise ValueError("render_particles cannot exceed particles")
        if self.source_strength_max_uSv_h <= self.source_strength_min_uSv_h:
            raise ValueError("source strength bounds are not ordered")
        if self.background_max_uSv_h <= self.background_min_uSv_h:
            raise ValueError("background bounds are not ordered")
        return self


class AdaptiveGridConfig(ConfigModel):
    type: Literal["quadtree"] = "quadtree"
    far_cell_m: float = 1.0
    default_cell_m: float = 0.5
    near_cell_m: float = 0.25
    minimum_cell_m: float = 0.25
    maximum_leaves: int = 5000
    refine_relative_variation: float = 0.15
    posterior_mass_refine: float = 0.002
    merge_hysteresis_updates: int = 5
    observation_cell_m: float = 0.25
    probability_threshold_uSv_h: float = 1.0

    @field_validator(
        "far_cell_m",
        "default_cell_m",
        "near_cell_m",
        "minimum_cell_m",
        "observation_cell_m",
    )
    @classmethod
    def positive_size(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("cell sizes must be positive")
        return value

    @model_validator(mode="after")
    def ordered_sizes(self) -> AdaptiveGridConfig:
        if not self.minimum_cell_m <= self.near_cell_m <= self.default_cell_m <= self.far_cell_m:
            raise ValueError("cell sizes must satisfy minimum <= near <= default <= far")
        if self.maximum_leaves < 4:
            raise ValueError("maximum_leaves must be at least four")
        return self


class ResidualConfig(ConfigModel):
    method: Literal["local_idw"] = "local_idw"
    neighbors: int = 8
    power: float = 2.0
    maximum_support_cells: float = 3.0
    minimum_effective_observations: float = 0.25
    maximum_relative_correction: float = Field(default=0.20, ge=0.0, le=1.0)


class CadenceConfig(ConfigModel):
    posterior_update_hz: float = 1.0
    map_update_hz: float = 1.0
    ui_animation_hz: float = 20.0
    persistence_flush_s: float = 2.0
    maximum_pose_history_s: float = 120.0

    @field_validator(
        "posterior_update_hz",
        "map_update_hz",
        "ui_animation_hz",
        "persistence_flush_s",
        "maximum_pose_history_s",
    )
    @classmethod
    def positive_rate(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("cadence values must be positive")
        return value


class DashboardConfig(ConfigModel):
    color_scale: str = "Turbo"
    scale_mode: Literal[
        "auto",
        "fixed",
        "log_fixed",
        "public_reference",
        "regulatory_reference",
    ] = "log_fixed"
    scale_min_uSv_h: float = 0.0
    scale_max_uSv_h: float = 3.5
    public_reference_rate_uSv_h: float = PUBLIC_CONTINUOUS_REFERENCE_RATE_USV_H
    ioe_reference_hours_per_year: float = IOE_REFERENCE_HOURS_PER_YEAR
    ioe_recording_rate_uSv_h: float = IOE_RECORDING_EQUIVALENT_RATE_USV_H
    ioe_investigation_rate_uSv_h: float = IOE_INVESTIGATION_EQUIVALENT_RATE_USV_H
    ioe_limit_rate_uSv_h: float = IOE_LIMIT_EQUIVALENT_RATE_USV_H
    ioe_maximum_rate_uSv_h: float = IOE_MAXIMUM_EQUIVALENT_RATE_USV_H
    subtract_background_for_scale: bool = False
    show_truth_field: bool = False
    show_truth_sources: bool = False
    show_measured_points: bool = True
    show_coverage: bool = True


class ScenarioConfig(ConfigModel):
    schema_version: str = "1.1"
    application: ApplicationConfig = Field(default_factory=ApplicationConfig)
    mission: MissionConfig = Field(default_factory=MissionConfig)
    world: WorldConfig = Field(default_factory=WorldConfig)
    pose: PoseProviderConfig = Field(default_factory=PoseProviderConfig)
    robot: RobotConfig = Field(default_factory=RobotConfig)
    trajectory: TrajectoryConfig = Field(default_factory=TrajectoryConfig)
    odometry: OdometryConfig = Field(default_factory=OdometryConfig)
    radiation_sources: list[RadiationSourceConfig] = Field(default_factory=list)
    detectors: list[DetectorConfig] = Field(default_factory=lambda: [DetectorConfig()])
    synchronization: SynchronizationConfig = Field(default_factory=SynchronizationConfig)
    mapping: MappingConfig = Field(default_factory=MappingConfig)
    inference: InferenceConfig = Field(default_factory=InferenceConfig)
    grid: AdaptiveGridConfig = Field(default_factory=AdaptiveGridConfig)
    residual: ResidualConfig = Field(default_factory=ResidualConfig)
    cadence: CadenceConfig = Field(default_factory=CadenceConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)

    @model_validator(mode="after")
    def unique_ids_and_inside_world(self) -> ScenarioConfig:
        source_ids = [source.id for source in self.radiation_sources]
        detector_ids = [detector.sensor_id for detector in self.detectors]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("radiation source IDs must be unique")
        if len(detector_ids) != len(set(detector_ids)):
            raise ValueError("detector IDs must be unique")
        if not self.detectors:
            raise ValueError("at least one detector is required")
        return self

    def canonical_yaml(self) -> str:
        data = self.model_dump(mode="json")
        return yaml.safe_dump(data, sort_keys=True, allow_unicode=True)

    def configuration_hash(self) -> str:
        return hashlib.sha256(self.canonical_yaml().encode()).hexdigest()


def load_scenario(path: str | Path) -> ScenarioConfig:
    scenario_path = Path(path)
    with scenario_path.open(encoding="utf-8") as stream:
        raw = yaml.safe_load(stream) or {}
    return ScenarioConfig.model_validate(raw)


def load_scenario_text(text: str) -> ScenarioConfig:
    raw: dict[str, Any] = yaml.safe_load(text) or {}
    return ScenarioConfig.model_validate(raw)


def save_scenario(config: ScenarioConfig, path: str | Path) -> None:
    Path(path).write_text(config.canonical_yaml(), encoding="utf-8")
