"""Never confuse a started container with a working installed HTTP application."""

import importlib.util
import json
import socket
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "integration_readiness", ROOT / "tools/integration/check_services.py"
)
checks = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checks)


def states(mode="simulacao", robot=True, detector=True):
    return (
        {"modo": mode, "robo": {"conectado": robot}, "radiacao": {"conectado": detector}},
        {"detector": {"estado": "conectado" if detector else "desconectado"}, "published": 3},
    )


@pytest.fixture
def clock(monkeypatch):
    elapsed = [0.0]

    def sleep(seconds):
        elapsed[0] += seconds

    monkeypatch.setattr(checks.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(checks.time, "sleep", sleep)


def test_missing_packaged_assets_are_not_reported_ready(monkeypatch):
    state, source = states()
    responses = {
        checks.PANEL + "/": b"<html>no canvas</html>",
        checks.PANEL + "/static/approved/renderer.js": b"drawRobot",
        checks.PANEL + "/api/estado": json.dumps(state).encode(),
        checks.USB + "/health": json.dumps(source).encode(),
    }
    monkeypatch.setattr(checks, "get", responses.__getitem__)
    with pytest.raises(ValueError, match="incompletos"):
        checks.probe()


def test_connection_refused_never_prints_ready(monkeypatch, clock, capsys):
    def refused():
        raise OSError("Connection refused")

    monkeypatch.setattr(checks, "probe", refused)
    assert checks.wait_ready("usb-simulado", 1) == 1
    output = capsys.readouterr()
    assert "pronto" not in output.out and "Connection refused" in output.err


def test_available_panel_is_distinct_from_confirmed_usb(monkeypatch, clock, capsys):
    monkeypatch.setattr(checks, "probe", lambda: states(detector=False))
    assert checks.wait_ready("usb-simulado", 30) == 0
    output = capsys.readouterr().out
    assert "Painel ARES pronto" in output and "USB ainda não confirmada" in output
    assert "Radiacode USB conectado" not in output


def test_simulation_requires_robot_initialized(monkeypatch, clock, capsys):
    monkeypatch.setattr(checks, "probe", lambda: states(robot=False))
    assert checks.wait_ready("usb-simulado", 1) == 1
    output = capsys.readouterr()
    assert "pronto" not in output.out and "Robô simulado" in output.err


def test_real_mode_panel_does_not_require_physical_robot(monkeypatch, clock, capsys):
    monkeypatch.setattr(checks, "probe", lambda: states(mode="real", robot=False))
    assert checks.wait_ready("usb-robo", 1) == 0
    output = capsys.readouterr().out
    assert "Painel ARES pronto" in output and "Radiacode USB conectado" in output
    assert "Aguardando Go2" in output


def test_recently_closed_connection_does_not_block_restart():
    with socket.socket() as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        port = server.getsockname()[1]
        server.listen(1)
        with socket.create_connection(("127.0.0.1", port)) as client:
            peer, _ = server.accept()
            peer.close()
            assert client.recv(1) == b""
    checks.free_ports((port,))


def test_listening_process_still_blocks_startup():
    with socket.socket() as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        port = server.getsockname()[1]
        server.listen(1)
        with pytest.raises(RuntimeError, match="ocupada"):
            checks.free_ports((port,))
