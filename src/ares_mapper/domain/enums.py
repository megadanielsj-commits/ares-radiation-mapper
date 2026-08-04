"""Enumerations used by the ARES data contracts."""

from enum import Enum


class StrEnum(str, Enum):
    """Python 3.10-compatible string enumeration."""


class MissionState(StrEnum):
    IDLE = "IDLE"
    READY = "READY"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPING = "STOPPING"
    COMPLETED = "COMPLETED"
    FAULT = "FAULT"


class Quality(StrEnum):
    VALID = "VALID"
    DEGRADED = "DEGRADED"
    INVALID = "INVALID"
    STALE = "STALE"


class MappingQuality(StrEnum):
    VALID = "VALID"
    DEGRADED = "DEGRADED"
    REJECTED = "REJECTED"


class SyncMethod(StrEnum):
    EXACT = "EXACT"
    LINEAR_SLERP = "LINEAR_SLERP"
    NEAREST = "NEAREST"
    NONE = "NONE"


class HealthState(StrEnum):
    STARTING = "STARTING"
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    DISCONNECTED = "DISCONNECTED"
    STOPPED = "STOPPED"
    FAULT = "FAULT"


class IdentifiabilityState(StrEnum):
    """Operational interpretation of the current source posterior."""

    INSUFFICIENT = "INSUFFICIENT"
    MULTIMODAL = "MULTIMODAL"
    CONVERGING = "CONVERGING"
    STABLE = "STABLE"
    MODEL_MISMATCH = "MODEL_MISMATCH"


class ObservationMode(StrEnum):
    """Exactly one radiological evidence channel used by an update."""

    DOSE_RATE_ROBUST = "dose_rate_robust"
    COUNTS_POISSON = "counts_poisson"
    COUNTS_NEGATIVE_BINOMIAL = "counts_negative_binomial"


class EvidenceKind(StrEnum):
    """Origin of an observation without implying statistical independence."""

    INSTANTANEOUS = "instantaneous"
    CUMULATIVE_RECOVERY = "cumulative_recovery"
    TIMED_DOSE = "timed_dose"
