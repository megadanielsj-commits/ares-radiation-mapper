import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ares_mapper.api.app import create_app
from ares_mapper.config import ScenarioConfig
from ares_mapper.core.mission_controller import MissionController


def test_dashboard_and_api_are_served(short_scenario: ScenarioConfig) -> None:
    app = create_app(
        MissionController(short_scenario),
        scenario_directory=Path("config/scenarios"),
    )
    with TestClient(app) as client:
        dashboard = client.get("/")
        assert dashboard.status_code == 200
        assert "ARES Radiation Mapper" in dashboard.text
        assert "Taxa da fonte a 1 metro" in dashboard.text
        assert "Dose acumulada" in dashboard.text
        assert "Posicionar fonte no mapa" not in dashboard.text
        assert 'id="map-layer"' not in dashboard.text
        assert "cdn" not in dashboard.text.lower()
        assert '<canvas\n          id="radiation-map"' in dashboard.text
        assert "{{INLINE_STYLES}}" not in dashboard.text
        assert "{{INLINE_APP}}" not in dashboard.text
        assert "/static/styles.css" not in dashboard.text
        assert "/static/app.js" not in dashboard.text
        assert "Plotly" not in dashboard.text
        assert "Canvas" in dashboard.text
        assert "observedMaximum" not in dashboard.text
        assert 'max="10000"' in dashboard.text
        assert 'value="10"' in dashboard.text
        assert "<b>mSv/h</b>" in dashboard.text
        assert "GRADIENTE ESTIMADO · ESCALA LOGARÍTMICA DA MISSÃO" in dashboard.text
        assert "Cores: intensidade relativa · referências CNEN no cursor" in (dashboard.text)
        assert "ESCALA REGULATÓRIA ABSOLUTA" not in dashboard.text
        assert "{position: 0.00, rgb: [11, 27, 42]}" in dashboard.text
        assert "{position: 0.35, rgb: [57, 151, 145]}" in dashboard.text
        assert "{position: 1.00, rgb: [183, 35, 58]}" in dashboard.text
        assert "publicReferenceRateUSvH" in dashboard.text
        assert "ioeMaximumRateUSvH" in dashboard.text
        assert "publicReferenceFraction" not in dashboard.text
        assert "doseRateMSvH * microSievertsPerMilliSievert" in dashboard.text
        assert "function robotGeometry()" in dashboard.text
        assert "minimum_display_length_px" in dashboard.text
        assert "visual_smoothing_time_constant_s" in dashboard.text
        assert "function shortestAngleDelta" in dashboard.text
        assert "displayPoseForFrame" in dashboard.text
        assert dashboard.headers["cache-control"] == "no-store, max-age=0"

        status = client.get("/api/v1/status")
        assert status.status_code == 200
        assert status.json()["state"] == "READY"

        scenarios = client.get("/api/v1/scenarios")
        assert scenarios.status_code == 200
        assert len(scenarios.json()["items"]) >= 6


def test_minimal_start_uses_exact_source_coordinates(
    short_scenario: ScenarioConfig,
) -> None:
    controller = MissionController(short_scenario)
    app = create_app(controller)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/simulation/start",
            json={
                "x_m": 1.75,
                "y_m": 5.68,
                "dose_rate_at_1m_uSv_h": 2.5,
            },
        )
        assert response.status_code == 200
        source_payload = response.json()["source"]
        assert source_payload["x_m"] == 1.75
        assert source_payload["y_m"] == 5.68
        assert source_payload["dose_rate_at_1m_uSv_h"] == 2.5

        configured = controller.scenario.radiation_sources[0]
        assert len(configured.position_keyframes) == 1
        assert len(configured.strength_keyframes) == 1
        assert configured.position_keyframes[0].x_m == 1.75
        assert configured.position_keyframes[0].y_m == 5.68
        assert configured.strength_keyframes[0].dose_rate_at_reference_uSv_h == 2.5
        assert controller.field is not None
        assert controller.scenario.inference.source_strength_min_uSv_h == pytest.approx(0.025)
        assert controller.scenario.inference.source_strength_max_uSv_h == pytest.approx(250.0)
        rate_at_1m = controller.field.dose_rate(
            2.75,
            5.68,
            configured.position_keyframes[0].z_m,
            0.0,
        )
        expected = short_scenario.world.background.dose_rate_uSv_h + 2.5
        assert rate_at_1m == pytest.approx(expected)


def test_high_intensity_simulation_expands_the_inference_range(
    short_scenario: ScenarioConfig,
) -> None:
    controller = MissionController(short_scenario)
    controller.configure_static_simulation_source(
        x_m=4.0,
        y_m=4.0,
        dose_rate_at_1m_uSv_h=100_000.0,
    )
    assert controller.scenario.inference.source_strength_min_uSv_h == pytest.approx(1_000.0)
    assert controller.scenario.inference.source_strength_max_uSv_h == pytest.approx(10_000_000.0)


def test_simulation_accepts_10_sv_h_and_rejects_values_above_it(
    short_scenario: ScenarioConfig,
) -> None:
    controller = MissionController(short_scenario)
    configured = controller.configure_static_simulation_source(
        x_m=4.0,
        y_m=4.0,
        dose_rate_at_1m_uSv_h=10_000_000.0,
    )
    assert configured["dose_rate_at_1m_uSv_h"] == 10_000_000.0
    assert controller.scenario.inference.source_strength_max_uSv_h == pytest.approx(1_000_000_000.0)
    assert controller.scenario.dashboard.color_scale == "AresClassic"
    assert controller.scenario.dashboard.scale_mode == "log_fixed"
    assert controller.scenario.dashboard.scale_min_uSv_h == pytest.approx(0.1)
    assert controller.scenario.dashboard.scale_max_uSv_h == pytest.approx(40_000_000.1)
    assert controller.scenario.dashboard.ioe_recording_rate_uSv_h == 0.5
    assert controller.scenario.dashboard.ioe_investigation_rate_uSv_h == 3.0
    assert controller.scenario.dashboard.ioe_limit_rate_uSv_h == 10.0
    assert controller.scenario.dashboard.ioe_maximum_rate_uSv_h == 25.0
    assert controller.scenario.dashboard.subtract_background_for_scale is False
    with pytest.raises(ValueError, match="cannot exceed"):
        controller.configure_static_simulation_source(
            x_m=4.0,
            y_m=4.0,
            dose_rate_at_1m_uSv_h=10_000_000.1,
        )


def test_websocket_emits_initial_state(short_scenario: ScenarioConfig) -> None:
    app = create_app(MissionController(short_scenario))
    with (
        TestClient(app) as client,
        client.websocket_connect("/api/v1/ws/telemetry") as websocket,
    ):
        message = websocket.receive_json()
        assert message["type"] == "mission_state"
        assert message["payload"]["state"] == "READY"


@pytest.mark.asyncio
async def test_probabilistic_products_are_available_from_api(
    short_scenario: ScenarioConfig,
) -> None:
    controller = MissionController(short_scenario)
    await controller.start()
    await controller.wait_until_complete()
    app = create_app(controller)
    with TestClient(app) as client:
        posterior = client.get("/api/v1/posterior/latest")
        assert posterior.status_code == 200
        assert posterior.json()["particle_count"] == short_scenario.inference.particles
        exposure = client.get("/api/v1/exposure")
        assert exposure.status_code == 200
        assert exposure.json()["cumulative_detector_dose_uSv"] >= 0
        map_payload = client.get("/api/v1/map/latest").json()
        assert "uncertainty" in map_payload["layers"]
        assert "source_probability" in map_payload["layers"]
        assert map_payload["sample_count"] >= 1
        assert any(
            value is not None and math.isfinite(value) for value in map_payload["values_row_major"]
        )
