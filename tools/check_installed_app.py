#!/usr/bin/env python3
"""Verify packaged web assets and HTTP startup without physical hardware."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request


def check(*, check_http=True, check_robot_imports=False):
    import ares
    from ares.servidor.app import ESTATICO
    for name in ("index.html", "app.js"):
        path = ESTATICO / name
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"Arquivo do painel ausente da instalação: {path}")
    result = {"package": str(Path(ares.__file__).resolve()), "web_assets": "ok",
              "physical_hardware_test": False}
    if check_robot_imports:
        # Follow the original driver's import path: its audio compatibility
        # layer must run before importing the SDK installed with --no-deps.
        from ares.robo.go2 import _cv2_disponivel, _sport_cmd_padrao
        commands = _sport_cmd_padrao()
        if not commands or not _cv2_disponivel():
            raise RuntimeError("Dependências do driver Go2/câmera indisponíveis")
        result["robot_driver_imports"] = "ok"
    if not check_http:
        return result
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="ares-installed-http-") as directory:
        environment = dict(os.environ)
        environment.update(ARES_MODO="simulacao", ARES_HOST="127.0.0.1", ARES_PORTA=str(port),
                           ARES_DADOS=directory, ARES_FONTE_RADIACAO="radiacode",
                           ARES_RADIACODE_URL="ws://127.0.0.1:0/ws")
        with (Path(directory)/"server.log").open("w+") as log:
            child = subprocess.Popen([sys.executable, "-m", "ares"], cwd=directory,
                                     env=environment, stdout=log, stderr=subprocess.STDOUT)
            # Bypass proxy configuration for local service probes.
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            try:
                deadline = time.monotonic()+15
                while True:
                    if child.poll() is not None:
                        raise RuntimeError(f"Aplicação instalada encerrou: {child.returncode}")
                    try:
                        with opener.open(f"http://127.0.0.1:{port}/", timeout=1) as r:
                            page = r.read().decode()
                            assert r.status == 200 and 'id="mapa"' in page
                        with opener.open(f"http://127.0.0.1:{port}/static/app.js", timeout=1) as r:
                            assert r.status == 200 and "desenharRobo" in r.read().decode()
                        with opener.open(f"http://127.0.0.1:{port}/api/estado", timeout=1) as r:
                            state = json.load(r)
                            assert state["modo"] == "simulacao" and state["robo"]["conectado"]
                        result.update(http_panel="ok", javascript="ok", api="ok", simulated_robot="ok")
                        return result
                    except (OSError, ValueError, AssertionError):
                        if time.monotonic() >= deadline:
                            raise RuntimeError("A aplicação não respondeu ao teste HTTP")
                        time.sleep(.1)
            except Exception:
                log.flush()
                log.seek(0)
                print(log.read(), file=sys.stderr)
                raise
            finally:
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets-only", action="store_true")
    parser.add_argument("--robot-imports", action="store_true")
    arguments = parser.parse_args()
    print(json.dumps(check(check_http=not arguments.assets_only,
                           check_robot_imports=arguments.robot_imports), indent=2, ensure_ascii=False))
