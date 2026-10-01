"""Teste do modo separado com o pacote ares da integração, sem dispositivos."""
import csv
import importlib.util
import io
from pathlib import Path
import time

from fastapi.testclient import TestClient

spec = importlib.util.spec_from_file_location("source_demo", Path(__file__).with_name("server.py"))
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


def test_demo_uses_original_panel_and_only_simulated_devices(tmp_path):
    with TestClient(demo.create_app(str(tmp_path))) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="radiation-map"' in page.text
        assert "FONTE E ROBÔ SIMULADOS" in page.text
        assert 'id="sim-strength"' in page.text
        for path in ("/static/approved/renderer.js", "/static/approved/integration.js",
                     "/static/approved/styles.css", "/simulation/adapter.js", "/simulation/field.js"):
            assert client.get(path).status_code == 200
        state = client.get("/api/estado").json()
        assert state["modo"] == "simulacao"
        assert state["radiacao"]["detector_id"] == "sim-1"
        assert state["fonte_sim"] == {"x": 4.0, "y": 3.0, "s": 8.0}
        assert state["robo"]["conectado"]
        assert "window.ARES_SIMULATION_MODEL" in page.text
        assert "Campo estimado pelas medições" in page.text


def test_source_changes_actual_simulated_counts(tmp_path):
    with TestClient(demo.create_app(str(tmp_path))) as client:
        assert client.post("/api/simulacao/fonte", json={"x": 0, "y": 0, "s": 8}).status_code == 200
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            reading = client.get("/api/estado").json().get("leitura")
            if reading is not None:
                break
            time.sleep(0.05)
        assert reading["cps"] > 1000  # Média de 10252 CPS junto à fonte.
        ts = reading["ts"]
        assert client.post("/api/simulacao/fonte", json={"x": 100, "y": 100, "s": 8}).status_code == 200
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            far = client.get("/api/estado").json().get("leitura")
            if far is not None and far["ts"] > ts:
                break
            time.sleep(0.05)
        assert far["cps"] < 100
        assert client.post("/api/simulacao/fonte", json={"x": 0, "y": 0, "s": 0}).status_code == 400


def test_simulated_mission_teleop_and_export(tmp_path):
    data = tmp_path / "simulacao"
    with TestClient(demo.create_app(str(data))) as client:
        deadline = time.monotonic() + 2
        while client.get("/api/estado").json().get("pose") is None:
            assert time.monotonic() < deadline
            time.sleep(.05)
        response = client.post("/api/missao/iniciar", json={"nome": "Fonte e robô simulados"})
        assert response.status_code == 200
        mission = response.json()["id"]
        with client.websocket_connect("/ws/comando") as ws:
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                ws.send_json({"vx": .45, "vy": 0, "vyaw": 0})
                time.sleep(.1)
                state = client.get("/api/estado").json()
                if state["missao"]["n_amostras"] >= 2:
                    break
            assert state["pose"]["x"] > .3
            assert state["missao"]["n_amostras"] >= 2
        assert client.post("/api/missao/encerrar").status_code == 200
        grade = client.get("/api/estado").json()["mapa"]
        assert grade["unidade"] == "µSv/h" and grade["cps_por_usvh"] == 80
        assert sum(v is not None for column in grade["valores"] for v in column) > 2
        saved = client.get(f"/api/missoes/{mission}.json").json()
        assert saved["missao"]["fonte_sim"] == {"x": 4., "y": 3., "s": 8.}
        rows = list(csv.DictReader(io.StringIO(client.get(f"/api/missoes/{mission}/amostras.csv").text)))
        assert len(rows) >= 2 and all(float(row["x"]) >= 0 for row in rows)
    spec_export = importlib.util.spec_from_file_location("demo_export", Path(__file__).parents[1]/"integration/export_sessions.py")
    exporter = importlib.util.module_from_spec(spec_export)
    spec_export.loader.exec_module(exporter)
    assert len(exporter.export(tmp_path)) == 2
