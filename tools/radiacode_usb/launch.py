#!/usr/bin/env python3
"""Launch independent USB recording, then ARES with virtual pose only."""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import uuid

import yaml

ROOT = Path(__file__).resolve().parents[2]


def make_scenario(readings, output, duration):
    scenario = yaml.safe_load((ROOT / "config/scenarios/static_source.yaml").read_text())
    scenario["application"].update(name="ARES — Teste USB Radiacode / Go2 virtual",
                                   data_directory=str(output / "missions"))
    scenario["mission"].update(name="radiacode-usb-posicao-simulada", mode="hybrid_usb_test",
                               duration_s=duration, simulation_speed=1.0)
    scenario["radiation_sources"] = []
    detector = scenario["detectors"][0]
    detector.update(sensor_id="radiacode_110_usb", source_type="radiacode_jsonl",
                    live_jsonl_path=str(readings), response_mode="dose_direct",
                    response_time_constant_s=0.0, response_compensation_enabled=False,
                    fixed_latency_ms=0.0, observation_mode="dose_rate_robust",
                    calibration_id="radiacode-scale-unverified-virtual-position")
    # These count-to-dose constants are not measured for the 110. In dose_direct
    # mode they are unused; remove inherited FS5000 values from the saved YAML.
    detector.pop("cpm_per_uSv_h", None)
    detector.pop("sensitivity_cps_per_uSv_h", None)
    scenario["synchronization"].update(radiation_latency_ms=0,
                                       radiation_time_uncertainty_ms=500)
    scenario["dashboard"].update(show_truth_sources=False, show_truth_field=False)
    return scenario


def stop_process(process):
    if process is None or process.poll() is not None:
        return
    process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--duration", type=float, default=3600)
    parser.add_argument("--dose-scale", type=float, default=10000)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not math.isfinite(args.duration) or args.duration <= 0:
        parser.error("duration deve ser positiva e finita")
    if not math.isfinite(args.dose_scale) or args.dose_scale <= 0:
        parser.error("dose-scale deve ser positiva e finita")
    if not 1 <= args.port <= 65535:
        parser.error("port deve estar entre 1 e 65535")
    # Fail before opening USB if the HTTP port is already in use.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", args.port))
    name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    output = ROOT / "resultados" / name
    output.mkdir(parents=True)
    recorder_dir = output / "detector"
    command = [sys.executable, "-u", str(ROOT / "tools/radiacode_usb/reader.py"),
               "--output", str(recorder_dir), "--seconds", "0",
               "--dose-scale", str(args.dose_scale)]
    if args.serial:
        command += ["--serial", args.serial]
    recorder = None
    dashboard = None
    log = None
    try:
        recorder = subprocess.Popen(command, cwd=ROOT, start_new_session=True)
        print("Aguardando a primeira leitura USB real antes de abrir o mapa...", flush=True)
        readings = recorder_dir / "readings.jsonl"
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if recorder.poll() is not None:
                raise RuntimeError("Leitor USB encerrou. Confira a mensagem e os arquivos de diagnóstico.")
            if readings.exists() and readings.stat().st_size > 0:
                # Flush can race with a read: require a complete JSON line.
                with readings.open() as stream:
                    first = stream.readline()
                if first.endswith("\n"):
                    row = json.loads(first)
                    if row.get("source") == "radiacode_usb":
                        break
            time.sleep(0.2)
        else:
            raise TimeoutError("Não chegou leitura real em 45 s; o mapa não foi iniciado")
        scenario = output / "scenario-usb.yaml"
        scenario.write_text(yaml.safe_dump(make_scenario(readings, output, args.duration),
                                           allow_unicode=True, sort_keys=False))
        log = (output / "dashboard.log").open("w")
        cmd = [str(Path(sys.executable).parent / "ares-map"), "run", "--scenario", str(scenario),
               "--host", "127.0.0.1", "--port", str(args.port), "--auto-start"]
        if args.no_browser:
            cmd += ["--no-open-browser"]
        dashboard = subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                     start_new_session=True)
        print(f"Abra http://127.0.0.1:{args.port} | RADIAÇÃO REAL + POSIÇÃO SIMULADA", flush=True)
        print(f"Resultados: {output}\nCtrl+C encerra o teste.", flush=True)
        end = time.monotonic() + args.duration
        dashboard_failed = False
        while time.monotonic() < end:
            if recorder.poll() is not None:
                print("Leitor USB encerrou. Parando painel; dados já gravados foram preservados.", flush=True)
                return 1
            if dashboard.poll() is not None and not dashboard_failed:
                print("Painel encerrou: consulte dashboard.log. A aquisição USB CONTINUA; Ctrl+C para parar.", flush=True)
                dashboard_failed = True
            time.sleep(0.25)
        return int(dashboard_failed)
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(f"FALHA: {exc}", file=sys.stderr)
        return 1
    finally:
        stop_process(recorder)
        stop_process(dashboard)
        if log:
            log.close()


if __name__ == "__main__":
    raise SystemExit(main())
