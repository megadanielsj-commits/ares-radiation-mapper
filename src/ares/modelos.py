"""Modelos de dados centrais: pose do robô, leitura do detector e amostra."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Pose:
    """Pose do robô no referencial de odometria (`odom`)."""

    ts: float
    x: float
    y: float
    yaw: float


@dataclass(frozen=True)
class Leitura:
    """Uma leitura do detector de radiação."""

    ts: float
    dr_usvh: float
    cpm: int
    cps: int
    dose_usv: float
    detector_id: str


@dataclass(frozen=True)
class Amostra:
    """Leitura já posicionada (posição do detector no instante efetivo)."""

    ts: float
    x: float
    y: float
    dr_usvh: float
    cpm: int
    lacuna_pose_s: float
