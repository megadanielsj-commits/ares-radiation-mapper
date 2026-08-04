from pathlib import Path

import pytest

from ares_mapper.config import load_scenario
from ares_mapper.runtime import (
    RuntimeMode,
    load_runtime_scenario,
    validate_runtime_pairing,
)


def test_simulation_mode_uses_only_simulated_inputs() -> None:
    path, config = load_runtime_scenario(RuntimeMode.SIMULATION)

    assert path == Path("config/scenarios/static_source.yaml")
    assert config.pose.provider in {"manual_sim", "simulated"}
    assert all(detector.source_type == "simulated" for detector in config.detectors)


def test_hardware_mode_requires_network_interface() -> None:
    with pytest.raises(ValueError, match="network-interface"):
        load_runtime_scenario(RuntimeMode.HARDWARE)


def test_hardware_mode_always_pairs_go2_and_fs5000() -> None:
    path, config = load_runtime_scenario(
        RuntimeMode.HARDWARE,
        network_interface="enp2s0",
        serial_port="/dev/ttyUSB0",
    )

    assert path == Path("config/hardware/go2_fs5000.yaml")
    assert config.pose.provider == "unitree_sportmode"
    assert config.pose.network_interface == "enp2s0"
    assert len(config.detectors) == 1
    assert config.detectors[0].source_type == "fs5000_serial"
    assert config.detectors[0].serial_port == "/dev/ttyUSB0"


def test_hardware_mode_rejects_partial_configuration() -> None:
    config = load_scenario("config/scenarios/static_source.yaml")
    config.detectors[0].source_type = "fs5000_serial"

    with pytest.raises(ValueError, match="Go2 and FS-5000 together"):
        validate_runtime_pairing(config, RuntimeMode.HARDWARE)
