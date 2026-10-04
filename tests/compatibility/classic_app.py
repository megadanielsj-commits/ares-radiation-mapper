"""Run the original FS-5000 simulator and dashboard, without presentation adapters."""

import os
from pathlib import Path

from ares_mapper.api.app import create_app as create_original_app
from ares_mapper.config import load_scenario
from ares_mapper.core.mission_controller import MissionController

ROOT = Path(__file__).resolve().parents[2]


def create_app(data_dir=None):
    scenario_path = ROOT / "config/scenarios/static_source.yaml"
    config = load_scenario(scenario_path)
    config.application.data_directory = Path(
        data_dir or os.environ.get("ARES_DADOS", ROOT / "resultados/fonte-simulada")
    )
    config.application.open_browser = False
    return create_original_app(MissionController(config), scenario_directory=scenario_path.parent)
