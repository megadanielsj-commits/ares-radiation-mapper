"""Historical JSONL input scenario, used only by compatibility tests."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def make_scenario(readings, output, duration):
    scenario = yaml.safe_load((ROOT / "config/scenarios/static_source.yaml").read_text())
    scenario["application"].update(
        name="ARES — Teste USB Radiacode / Go2 virtual", data_directory=str(output / "missions")
    )
    scenario["mission"].update(
        name="radiacode-usb-posicao-simulada",
        mode="hybrid_usb_test",
        duration_s=duration,
        simulation_speed=1.0,
    )
    scenario["radiation_sources"] = []
    detector = scenario["detectors"][0]
    detector.update(
        sensor_id="radiacode_110_usb",
        source_type="radiacode_jsonl",
        live_jsonl_path=str(readings),
        response_mode="dose_direct",
        response_time_constant_s=0.0,
        response_compensation_enabled=False,
        fixed_latency_ms=0.0,
        observation_mode="dose_rate_robust",
        calibration_id="radiacode-scale-unverified-virtual-position",
    )
    # These count-to-dose constants are not measured for the 110. In dose_direct
    # mode they are unused; remove inherited FS5000 values from the saved YAML.
    detector.pop("cpm_per_uSv_h", None)
    detector.pop("sensitivity_cps_per_uSv_h", None)
    scenario["synchronization"].update(radiation_latency_ms=0, radiation_time_uncertainty_ms=500)
    scenario["dashboard"].update(show_truth_sources=False, show_truth_field=False)
    return scenario
