"""Input selection, unchanged map, real contracts and operator stop semantics."""
import asyncio
import csv
import io
import json
import time
import zipfile

from fastapi.testclient import TestClient
import pytest

from tools.operator_console.check_map_lock import check
from tools.operator_console.runtime import ROOT, LiveController
from tools.operator_console.server import create_app
from ares.modelos import Leitura
from ares.simulacao.robo import RoboSimulado
from ares_mapper.core.mission_controller import MissionController


class FakeRadiation:
    """Hardware contract double: independent CPS and reported dose, no calibration."""
    def __init__(self):
        self.callbacks = []
        self.connected = True
        self.task = None
        self.dose_rate = .22

    def assinar(self, callback):
        self.callbacks.append(callback)

    def estado(self):
        return {"conectado": self.connected, "erro": None if self.connected else "USB ausente"}

    async def iniciar(self):
        self.task = asyncio.create_task(self.run())

    async def encerrar(self):
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)

    async def run(self):
        while True:
            await asyncio.sleep(.2)
            if self.connected:
                reading = Leitura(time.time(), self.dose_rate, 6000, 100, None, "test-usb")
                for callback in self.callbacks:
                    callback(reading)


FACTORIES = {"real_robot": RoboSimulado, "real_radiation": FakeRadiation}


def wait_for(client, predicate, timeout=12):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        snapshot = client.get("/api/console/state").json()
        if predicate(snapshot):
            return snapshot
        time.sleep(.05)
    raise AssertionError(snapshot)


def test_map_and_original_input_cores_are_exactly_preserved():
    assert len(check()["files"]) >= 50
    original = (ROOT/"src/ares_mapper/web/templates/index.html").read_text()
    console = (ROOT/"tools/operator_console/static/index.html").read_text()
    marker = '<section class="panel map-panel"'
    original_map = original.split(marker, 1)[1].split("</section>", 1)[0]
    new_map = console.split(marker, 1)[1].split("</section>", 1)[0]
    assert new_map == original_map.replace("Mapa construído pelas medições", "Mapa de calor")


def test_default_is_exact_classic_simulator_with_no_hardware(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        runtime = app.state.console
        assert isinstance(runtime.active, MissionController)
        assert runtime.usb is None
        page = client.get("/").text
        assert (ROOT/"src/ares_mapper/web/static/app.js").read_text() in page
        assert "ares-logo.png" in page
        assert client.get("/console-static/ares-logo.png").content == (ROOT/"tools/operator_console/static/ares-logo.png").read_bytes()
        assert client.get("/api/console/state").json()["mode"] == "simulation"
        assert client.post("/api/v1/mission/control", json={"linear_m_s": 1, "yaw_rate_rad_s": 0}).status_code == 409
        assert client.post("/api/console/start", json={}, headers={"Origin":"https://external.example"}).status_code == 403


def test_classic_mission_controls_watchdog_export_and_mode_lock(tmp_path):
    app = create_app(tmp_path, manage_usb=False)
    with TestClient(app) as client:
        assert client.post("/api/console/start", json={}).status_code == 200
        assert client.post("/api/console/configure", json={"mode":"hardware"}).status_code == 409
        assert client.post("/api/console/control", json={"client":"one", "linear_m_s":.45}).status_code == 409
        assert client.post("/api/console/enable-control", json={"client":"one"}).status_code == 200
        assert client.post("/api/console/enable-control", json={"client":"two"}).status_code == 409
        assert client.post("/api/console/control", json={"client":"two", "linear_m_s":.45}).status_code == 409
        assert client.post("/api/console/control", json={"client":"one", "linear_m_s":.45}).status_code == 200
        wait_for(client, lambda s:not s["control_enabled"])
        assert app.state.console.active._manual_command["linear_m_s"] == 0
        assert client.get("/api/console/export").status_code == 409
        wait_for(client, lambda s:s["status"]["counts"]["mapped"] >= 2)
        assert client.post("/api/console/stop", json={}).status_code == 200
        response = client.get("/api/console/export")
        assert response.status_code == 200
        with zipfile.ZipFile(io.BytesIO(response.content)) as package:
            assert "exports/mapped_samples.csv" in package.namelist()
            assert "mission.json" in package.namelist()


@pytest.mark.parametrize("mode", ["usb_simulated_robot", "robot_simulated_source", "hardware"])
def test_mixed_and_real_modes_use_werik_inputs_v4_map_and_save(tmp_path, mode):
    app = create_app(tmp_path, FACTORIES, manage_usb=False)
    with TestClient(app) as client:
        assert client.post("/api/console/configure", json={"mode":mode}).status_code == 200
        runtime = app.state.console
        assert isinstance(runtime.active, LiveController)
        wait_for(client, lambda s:s["status"]["pose"] is not None and s["status"]["radiation"] is not None)
        assert client.post("/api/console/start", json={}).status_code == 200
        if mode != "usb_simulated_robot":
            assert client.post("/api/console/enable-control", json={"client":"one"}).status_code == 409
        assert client.post("/api/console/enable-control", json={"client":"one", "acknowledge_physical_robot":True}).status_code == 200
        assert client.post("/api/console/control", json={"client":"one", "linear_m_s":.45}).status_code == 200
        assert client.post("/api/console/brake", json={}).status_code == 200
        snapshot = wait_for(client, lambda s:s["status"]["counts"]["mapped"] >= 2)
        assert not snapshot["control_enabled"]
        assert client.post("/api/console/configure", json={"mode":"simulation"}).status_code == 409
        assert client.post("/api/console/stop", json={}).status_code == 200
        active = runtime.active
        metadata = json.loads((active.mission_directory/"mission.json").read_text())
        assert metadata["mode"] == mode
        assert metadata["samples"] >= 2
        assert active.latest_map.sample_count >= 2
        if mode != "robot_simulated_source":
            sample = active.worker.samples[0]
            assert sample.cps == 100
            assert sample.dose_rate_uSv_h_raw == .22  # reported rate, never raw CPS relabeled
            assert metadata["map_evidence"] == "reported_dose_rate"
            assert active.latest_map.unit == "uSv/h"
            assert metadata["map_unit"] == "uSv/h"
            assert metadata["map_display_unit"] == "mSv/h"
            assert active.latest_map.exposure.cumulative_robot_path_dose_uSv == pytest.approx(.22*len(active.worker.samples)/3600)
        response = client.get("/api/console/export")
        with zipfile.ZipFile(io.BytesIO(response.content)) as package:
            assert "amostras.csv" in package.namelist()
            assert "map_latest.json" in package.namelist()
            exported_map = json.loads(package.read("map_latest.json"))
            assert exported_map["unit"] == "uSv/h"
            assert exported_map["display_unit"] == "mSv/h"
            assert exported_map["display_factor_from_internal"] == .001
            if mode != "robot_simulated_source":
                rows = list(csv.DictReader(io.StringIO(package.read("amostras.csv").decode())))
                assert float(rows[0]["cps"]) == 100
                assert float(rows[0]["dr_usvh"]) == .22
        assert client.post("/api/console/configure", json={"mode":"simulation"}).status_code == 200
        assert isinstance(runtime.active, MissionController)


def test_usb_disconnect_is_visible_and_blocks_mission_start(tmp_path):
    app = create_app(tmp_path, FACTORIES, manage_usb=False)
    with TestClient(app) as client:
        client.post("/api/console/configure", json={"mode":"usb_simulated_robot"})
        rad = app.state.console.active.orq.radiacao
        rad.connected = False
        assert not client.get("/api/console/state").json()["radiation"]["conectado"]
        assert client.post("/api/console/start", json={}).status_code == 409
        rad.connected = True
        wait_for(client, lambda s:s["status"]["pose"] is not None and s["status"]["radiation"] is not None)
        assert client.post("/api/console/start", json={}).status_code == 200


def test_unavailable_reported_dose_blocks_start_and_skips_map_without_losing_raw_counts(tmp_path):
    app = create_app(tmp_path, FACTORIES, manage_usb=False)
    with TestClient(app) as client:
        client.post("/api/console/configure", json={"mode":"usb_simulated_robot"})
        active = app.state.console.active
        radiation = active.orq.radiacao
        radiation.dose_rate = None
        wait_for(client, lambda s:s["status"]["radiation"] is not None)
        assert client.post("/api/console/start", json={}).status_code == 409
        radiation.dose_rate = .22
        wait_for(client, lambda s:s["status"]["radiation"]["dose_rate_uSv_h"] == .22)
        assert client.post("/api/console/start", json={}).status_code == 200
        wait_for(client, lambda s:s["status"]["counts"]["mapped"] >= 2)
        radiation.dose_rate = None
        wait_for(client, lambda s:active.worker.skipped_dose_samples >= 2)
        mapped = len(active.worker.samples)
        skipped = active.worker.skipped_dose_samples
        wait_for(client, lambda s:active.worker.skipped_dose_samples >= skipped + 2)
        assert len(active.worker.samples) == mapped
        radiation.dose_rate = .44
        wait_for(client, lambda s:s["status"]["counts"]["mapped"] > mapped)
        client.post("/api/console/stop", json={})
        raw = json.loads((active.mission_directory/"mission_raw.json").read_text())
        assert any(a["dr_usvh"] is None and a["cps"] == 100 for a in raw["amostras"])
        assert len(raw["amostras"]) > len(active.worker.samples)
        assert active.worker.samples[-1].dose_rate_uSv_h_raw == .44


def test_invalid_mode_source_and_origin_leave_current_runtime_intact(tmp_path):
    app = create_app(tmp_path, FACTORIES, manage_usb=False)
    with TestClient(app) as client:
        assert client.post("/api/console/configure", json={"mode":"oops"}).status_code == 409
        assert client.post("/api/console/configure", json={"x_m":500}).status_code == 422
        assert client.post("/api/console/configure", json={"x_m":50}).status_code == 409
        assert app.state.console.mode == "simulation"


def test_shutdown_saves_live_mission(tmp_path):
    app = create_app(tmp_path, FACTORIES, manage_usb=False)
    with TestClient(app) as client:
        client.post("/api/console/configure", json={"mode":"hardware"})
        wait_for(client, lambda s:s["status"]["pose"] is not None and s["status"]["radiation"] is not None)
        client.post("/api/console/start", json={})
        wait_for(client, lambda s:s["status"]["counts"]["mapped"] >= 1)
        directory = app.state.console.mission_directory
    assert (directory/"amostras.csv").exists()
    assert json.loads((directory/"mission.json").read_text())["reason"] == "server_shutdown"


def test_nonzero_initial_real_odometry_centers_mission_and_map(tmp_path):
    def robot():
        result = RoboSimulado()
        result.x, result.y = 35, -21
        return result
    app = create_app(tmp_path, dict(FACTORIES, real_robot=robot), manage_usb=False)
    with TestClient(app) as client:
        client.post("/api/console/configure", json={"mode":"hardware"})
        wait_for(client, lambda s:s["status"]["pose"] is not None and s["status"]["radiation"] is not None)
        assert client.post("/api/console/start", json={}).status_code == 200
        config = client.get("/api/v1/scenario").json()
        assert config["world"]["bounds_m"] == {"x_min":25, "x_max":45, "y_min":-31, "y_max":-11}
        wait_for(client, lambda s:s["status"]["counts"]["mapped"] >= 1)
        client.post("/api/console/stop", json={})
        payload = client.get("/api/v1/map/latest").json()
        assert payload["unit"] == "uSv/h"
        assert 35 in payload["x_coordinates_m"]
        assert -21 in payload["y_coordinates_m"]


def test_telemetry_connection_and_json_use_same_runtime(tmp_path):
    app = create_app(tmp_path, manage_usb=False)
    with TestClient(app) as client:
        with client.websocket_connect("/api/v1/ws/telemetry", headers={"Origin":"http://127.0.0.1:8001"}) as ws:
            assert ws.receive_json()["type"] == "mission_state"
            client.post("/api/console/start", json={})
            event = ws.receive_json()
            assert event["type"] == "mission_state"
            assert event["payload"]["state"] == "RUNNING"
        assert len(app.state.console.event_bus._subscribers) == 0
