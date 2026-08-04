"""Two explicit runtime modes used by local and Docker execution."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from ares_mapper.config import ScenarioConfig, load_scenario


class RuntimeMode(str, Enum):
    """Public runtime choices for the ARES operator."""

    SIMULATION = "simulation"
    HARDWARE = "hardware"


MODE_SCENARIOS = {
    RuntimeMode.SIMULATION: Path("config/scenarios/static_source.yaml"),
    RuntimeMode.HARDWARE: Path("config/hardware/go2_fs5000.yaml"),
}


def validate_runtime_pairing(config: ScenarioConfig, mode: RuntimeMode) -> None:
    """Reject mixed input combinations from the public two-mode launcher."""

    if mode is RuntimeMode.SIMULATION:
        simulated_pose = config.pose.provider in {"manual_sim", "simulated"}
        simulated_radiation = bool(config.detectors) and all(
            detector.source_type == "simulated" for detector in config.detectors
        )
        if not simulated_pose or not simulated_radiation:
            raise ValueError("simulation mode requires simulated pose and simulated radiation")
        return

    real_pose = config.pose.provider == "unitree_sportmode"
    real_radiation = len(config.detectors) == 1 and (
        config.detectors[0].source_type == "fs5000_serial"
    )
    if not real_pose or not real_radiation:
        raise ValueError("hardware mode requires Unitree Go2 and FS-5000 together")


def load_runtime_scenario(
    mode: RuntimeMode,
    *,
    network_interface: str | None = None,
    serial_port: str = "auto",
) -> tuple[Path, ScenarioConfig]:
    """Load one of the two public modes and apply host-specific hardware values."""

    scenario_path = MODE_SCENARIOS[mode]
    config = load_scenario(scenario_path)
    validate_runtime_pairing(config, mode)

    if mode is RuntimeMode.HARDWARE:
        if network_interface is None or not network_interface.strip():
            raise ValueError("hardware mode requires --network-interface or ARES_NETWORK_INTERFACE")
        if not serial_port.strip():
            raise ValueError("hardware mode requires a valid FS-5000 serial port")
        config.pose.network_interface = network_interface.strip()
        config.detectors[0].serial_port = serial_port.strip()

    return scenario_path, config
