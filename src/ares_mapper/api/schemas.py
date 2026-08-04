"""Request bodies for operator actions."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ares_mapper.config import MAX_SIMULATION_SOURCE_STRENGTH_USV_H


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourcePatch(ApiModel):
    x_m: float | None = None
    y_m: float | None = None
    z_m: float | None = None
    strength_uSv_h: float | None = Field(default=None, ge=0)
    enabled: bool | None = None


class TrajectoryPatch(ApiModel):
    speed_m_s: float = Field(gt=0)


class SpeedPatch(ApiModel):
    speed: float = Field(gt=0, le=500)


class ManualControlRequest(ApiModel):
    linear_m_s: float = Field(ge=-1.5, le=1.5)
    yaw_rate_rad_s: float = Field(ge=-3.0, le=3.0)


class SimpleSimulationStartRequest(ApiModel):
    x_m: float
    y_m: float
    dose_rate_at_1m_uSv_h: float = Field(
        gt=0,
        le=MAX_SIMULATION_SOURCE_STRENGTH_USV_H,
    )


class StepRequest(ApiModel):
    delta_s: float = Field(default=0.1, gt=0, le=60)


class FaultRequest(ApiModel):
    target: str
    fault: str


class ExportRequest(ApiModel):
    include_truth: bool = True
