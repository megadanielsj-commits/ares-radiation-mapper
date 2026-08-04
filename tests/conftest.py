from __future__ import annotations

from pathlib import Path

import pytest

from ares_mapper.config import ScenarioConfig, load_scenario


@pytest.fixture()
def short_scenario(tmp_path: Path) -> ScenarioConfig:
    config = load_scenario("config/scenarios/static_source.yaml")
    config.mission.duration_s = 2.0
    config.mission.simulation_speed = 200.0
    config.application.data_directory = tmp_path / "missions"
    config.world.map_resolution_m = 0.25
    config.mapping.grid_resolution_m = 0.25
    config.mapping.refresh_rate_hz = 1.0
    return config
