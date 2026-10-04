#!/usr/bin/env python3
"""Local readiness checks: HTTP availability is separate from USB/robot status."""

from __future__ import annotations

import json
import socket
import sys
import time
import urllib.request

PANEL = "http://127.0.0.1:8001"
USB = "http://127.0.0.1:1098"


def get(url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=2) as response:
        return response.read()


def probe():
    page = get(PANEL + "/").decode()
    script = get(PANEL + "/static/approved/renderer.js").decode()
    state = json.loads(get(PANEL + "/api/estado"))
    source = json.loads(get(USB + "/health"))
    if 'id="radiation-map"' not in page or "drawRobot" not in script:
        raise ValueError("Arquivos do painel incompletos")
    return state, source


def wait_ready(mode, timeout):
    deadline = time.monotonic() + timeout
    error = None
    while time.monotonic() < deadline:
        try:
            state, source = probe()
            expected = "real" if mode == "usb-robo" else "simulacao"
            if state["modo"] != expected:
                raise ValueError(f"Modo incorreto: esperado {expected}, recebido {state['modo']}")
            if expected == "simulacao" and not state["robo"].get("conectado"):
                raise ValueError("Robô simulado ainda não inicializou")
            print(f"Painel ARES pronto: {PANEL}")
            # Do not make the web page depend on a physical Go2 connection.
            usb_deadline = min(deadline, time.monotonic() + 20)
            while (
                not (
                    source["detector"].get("estado") == "conectado"
                    and state["radiacao"].get("conectado")
                )
                and time.monotonic() < usb_deadline
            ):
                time.sleep(0.5)
                state, source = probe()
            state, source = probe()
            if source["detector"].get("estado") == "conectado" and state["radiacao"].get(
                "conectado"
            ):
                print(f"Radiacode USB conectado; contagens publicadas: {source['published']}.")
            else:
                print("Painel disponível; aquisição USB ainda não confirmada.")
                print("Estado USB:", json.dumps(source["detector"], ensure_ascii=False))
                print("Confira o cabo, a permissão e o relatório: bash ensaio verificar")
            if mode == "usb-robo" and not state["robo"].get("conectado"):
                print("Aguardando Go2: confira o Wi-Fi do robô. Nenhum movimento foi iniciado.")
            print(
                "Com detector e posição disponíveis, clique em Iniciar missão "
                "para gravar as amostras."
            )
            return 0
        except (OSError, ValueError, KeyError) as exc:
            error = str(exc)
            time.sleep(0.25)
    print(f"Falha ao iniciar painel/serviço: {error}", file=sys.stderr)
    return 1


def free_ports(ports=(8001, 1098)):
    for port in ports:
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                listener.bind(("127.0.0.1", port))
            except OSError as exc:
                raise RuntimeError(
                    f"Porta {port} já está ocupada. Encerre o processo que a utiliza."
                ) from exc


def report():
    for name, path in (
        ("Aquisição USB", USB + "/health"),
        ("Aplicação ARES", PANEL + "/api/estado"),
    ):
        try:
            print(name + ":\n" + json.dumps(json.loads(get(path)), ensure_ascii=False, indent=2))
        except Exception as exc:
            print(f"{name}: {exc}")
