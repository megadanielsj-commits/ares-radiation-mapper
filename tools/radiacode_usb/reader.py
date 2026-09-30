#!/usr/bin/env python3
"""Independent USB recorder. No robot, map, network service or simulator imports."""
from __future__ import annotations

import argparse
import csv
import dataclasses
import fcntl
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import signal
import sys
import time
import traceback
from datetime import datetime, timezone
from enum import Enum

try:
    from tools.radiacode_usb.counts import PairRawData
except ModuleNotFoundError:
    from counts import PairRawData


def serializable(value):
    if dataclasses.is_dataclass(value):
        return serializable(dataclasses.asdict(value))
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, Enum):
        return {"name": value.name, "value": value.value}
    if isinstance(value, dict):
        return {str(k): serializable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [serializable(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    return value


def json_line(stream, item):
    stream.write(json.dumps(serializable(item), ensure_ascii=False, allow_nan=False) + "\n")
    stream.flush()


def save_json(path, item):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(serializable(item), indent=2, ensure_ascii=False,
                                    allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def measurement(record, sequence, received_utc_ns, received_monotonic_ns, *, scale,
                session_id, serial, status, duplicate=False):
    """Preserve fractional CPS and raw dose. Scale is explicit and provisional."""
    cps, raw_rate = float(record.count_rate), float(record.dose_rate)
    if not all(math.isfinite(v) and v >= 0 for v in (cps, raw_rate)):
        raise ValueError("Taxa de dose/CPS negativa ou não finita recebida do detector")
    return {
        "schema_version": "ares-radiacode-usb-1",
        "kind": "measurement", "source": "radiacode_usb",
        "session_id": session_id, "serial_number": serial, "sequence": sequence,
        "timestamp_utc": datetime.fromtimestamp(received_utc_ns / 1e9,
                                               timezone.utc).isoformat(),
        "received_utc_ns": received_utc_ns,
        "received_monotonic_ns": received_monotonic_ns,
        "device_record_time_utc": serializable(record.dt),
        "device_time_origin": "radiacode_library_host_base_plus_device_offset",
        "dose_rate_raw": raw_rate, "dose_rate_scale": scale,
        "dose_rate_uSv_h": raw_rate * scale,
        "dose_conversion_verified": False,
        "cps": cps, "cpm_derived": cps * 60.0,
        "dose_rate_error_percent": record.dose_rate_err,
        "count_rate_error_percent": record.count_rate_err,
        "flags": record.flags, "real_time_flags": record.real_time_flags,
        "cumulative_dose_raw": status.get("dose"),
        "cumulative_dose_uSv": None,
        "status_record_time_utc": status.get("dt"),
        "battery_percent": status.get("charge_level"),
        "temperature_c": status.get("temperature"),
        "is_duplicate": duplicate,
        "position": None,
    }


CSV_FIELDS = ["timestamp_utc", "received_utc_ns", "received_monotonic_ns",
              "device_record_time_utc", "session_id", "serial_number", "sequence",
              "dose_rate_raw", "dose_rate_scale", "dose_rate_uSv_h",
              "dose_conversion_verified", "cps", "cpm_derived",
              "dose_rate_error_percent", "count_rate_error_percent",
              "cumulative_dose_raw", "cumulative_dose_uSv", "status_record_time_utc",
              "battery_percent", "temperature_c", "flags", "real_time_flags",
              "is_duplicate"]


def run(args, device_factory=None):
    from radiacode import RadiaCode, RealTimeData, RareData, RawData
    out = Path(args.output).resolve()
    # Each run must have its own folder: never append a different connection to old data.
    out.mkdir(parents=True, exist_ok=False)
    session_id = out.name
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    previous_signals = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        previous_signals[sig] = signal.signal(sig, stop)
    started = time.monotonic()
    deadline = started + args.seconds if args.seconds > 0 else float("inf")
    count = 0
    fresh_count = 0
    pairs = PairRawData()
    last_count = started
    latest_measurement = None
    result = "starting"
    device = None
    serial = None
    metadata = {"session_id": session_id, "transport": "USB", "source": "radiacode_usb",
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "python": sys.version, "platform": platform.platform(),
                "radiacode_version": importlib.metadata.version("radiacode"),
                "dose_rate_scale": args.dose_scale, "dose_conversion_verified": False,
                "dose_scale_reference": "cdump/radiacode examples/radiacode-exporter.py: 10000 * dose_rate",
                "dose_note": "Conversão provisória: comparar com o visor em Sv. Dose acumulada mantida bruta.",
                "timestamp_note": "UTC/monotônico de recebimento; dt da biblioteca deriva do relógio do host.",
                "initialization_note": "A biblioteca inicializa a sessão e ajusta o relógio do detector. Não zeramos dose/espectro nem alteramos alarmes.",
                "poll_interval_s": args.poll, "spectrum_interval_s": args.spectrum_interval}
    save_json(out / "session.json", metadata)
    print(f"Dados: {out}", flush=True)
    print("USB REAL | taxa convertida provisoriamente; comparar com visor em µSv/h", flush=True)
    lock_dir = Path(os.environ.get("ARES_RADIACODE_LOCK_DIR", f"/tmp/ares-radiacode-lock-{os.getuid()}"))
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock = (lock_dir / f"ares-radiacode-usb-{os.getuid()}.lock").open("a")
    files = []
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Outro leitor deste pacote já está usando o detector. Encerre-o primeiro.") from exc
        for name in ("raw_records.jsonl", "readings.jsonl", "spectra.jsonl", "events.jsonl", "counts_1s.jsonl"):
            files.append((out / name).open("w", encoding="utf-8", buffering=1))
        raw, readings, spectra, events, counts_file = files
        csvfile = (out / "readings.csv").open("w", encoding="utf-8", newline="", buffering=1)
        files.append(csvfile)
        writer = csv.DictWriter(csvfile, CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        factory = device_factory or RadiaCode
        device = factory(serial_number=args.serial)
        serial = device.serial_number()
        metadata.update(serial_number=serial, firmware=device.fw_version())
        # Optional metadata failures do not prevent acquiring real-time records.
        for name in ("configuration", "energy_calib", "get_alarm_limits"):
            try:
                metadata[name] = serializable(getattr(device, name)())
            except Exception as exc:
                metadata[name + "_error"] = f"{type(exc).__name__}: {exc}"
        save_json(out / "session.json", metadata)
        print(f"Conectado: {serial} | firmware {metadata['firmware']}", flush=True)
        status = {}
        newest_device_time = None
        last_sample = time.monotonic()
        next_spectrum = time.monotonic() + args.spectrum_interval
        result = "running"
        while not stopping and time.monotonic() < deadline:
            request_start_ns = time.monotonic_ns()
            records = device.data_buf()
            mono_ns, utc_ns = time.monotonic_ns(), time.time_ns()
            raw_records = [r for r in records if isinstance(r, RawData)]
            for record in records:
                envelope = {"type": type(record).__name__, "received_utc_ns": utc_ns,
                            "received_monotonic_ns": mono_ns,
                            "request_duration_ms": (mono_ns - request_start_ns) / 1e6,
                            "record": serializable(record)}
                json_line(raw, envelope)
                if isinstance(record, RareData):
                    status = serializable(record)
                if not isinstance(record, RealTimeData):
                    continue
                duplicate = newest_device_time is not None and record.dt <= newest_device_time
                count += 1
                row = measurement(record, count, utc_ns, mono_ns, scale=args.dose_scale,
                                  session_id=session_id, serial=serial, status=status,
                                  duplicate=duplicate)
                json_line(readings, row)
                writer.writerow(row)
                csvfile.flush()
                if not duplicate:
                    latest_measurement = row
                    newest_device_time = record.dt
                    fresh_count += 1
                    last_sample = time.monotonic()
                print(f"{row['timestamp_utc']}  #{count}  "
                      f"DR≈{row['dose_rate_uSv_h']:.6g} µSv/h  "
                      f"CPS={row['cps']:.4g}  CPM*={row['cpm_derived']:.4g}  "
                      f"raw={row['dose_rate_raw']:.8g}"
                      f"{' (repetida)' if duplicate else ''}", flush=True)
                if fresh_count == 1 and not duplicate:
                    print("PRIMEIRA LEITURA REAL RECEBIDA. CPM* = 60 × CPS.", flush=True)
            for record in raw_records:
                row = pairs.add(record, utc_ns, mono_ns, session_id, serial)
                if row is None:
                    continue
                row.update(timing_quality="batched_uncertain" if len(raw_records) > 2 else "live_receipt",
                           dose_rate_uSv_h=(latest_measurement or {}).get("dose_rate_uSv_h"),
                           dose_rate_raw=(latest_measurement or {}).get("dose_rate_raw"),
                           dose_conversion_verified=False, cumulative_dose_uSv=None)
                json_line(counts_file, row)
                last_count = time.monotonic()
            if getattr(args, "require_counts", False) and time.monotonic() - last_count > args.no_data_timeout:
                raise TimeoutError("Sem contagens RawData novas; integração CEIA não usa CPS suavizado")
            if time.monotonic() - last_sample > args.no_data_timeout:
                raise TimeoutError(f"Sem RealTimeData nova por {args.no_data_timeout:g} s; consulte raw_records.jsonl")
            if args.spectrum_interval > 0 and time.monotonic() >= next_spectrum:
                before = time.time_ns()
                try:
                    spectrum = device.spectrum()
                    coefs = [spectrum.a0, spectrum.a1, spectrum.a2]
                    energies = None
                    if isinstance(coefs, list) and len(coefs) == 3:
                        energies = [coefs[0] + coefs[1]*i + coefs[2]*i*i
                                    for i in range(len(spectrum.counts))]
                    json_line(spectra, {"kind": "spectrum", "request_start_utc_ns": before,
                                      "received_utc_ns": time.time_ns(),
                                      "duration_s": spectrum.duration.total_seconds(),
                                      "counts": spectrum.counts, "energy_keV": energies,
                                      "energy_calibration": coefs,
                                      "channel_count": len(spectrum.counts),
                                      "spectrum_semantics": "snapshot acumulado; não somar snapshots"})
                except Exception as exc:
                    json_line(events, {"event": "spectrum_error", "error": repr(exc),
                                       "received_utc_ns": time.time_ns()})
                    print(f"Espectro indisponível nesta consulta: {exc}", file=sys.stderr, flush=True)
                next_spectrum = time.monotonic() + args.spectrum_interval
            time.sleep(args.poll)
        if fresh_count == 0:
            raise TimeoutError("Nenhuma leitura RealTimeData nova recebida")
        result = "stopped" if stopping else "completed"
        return 0
    except Exception as exc:
        result = "error"
        (out / "error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        print(f"FALHA: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        if type(exc).__name__ == "NoBackendError":
            print("Falta libusb no sistema. No Ubuntu/Debian, execute 02_preparar_ambiente.sh.", file=sys.stderr)
        elif getattr(exc, "errno", None) in (13, -3):
            print("Sem permissão: execute 03_permissao_usb.sh e reconecte o cabo.", file=sys.stderr)
        print("Confira cabo de dados, permissão USB e feche outros leitores/apps. "
              "Envie diagnostico.txt, session.json e error.txt.", file=sys.stderr, flush=True)
        return 1
    finally:
        if device is not None:
            try:
                device.close()
            except Exception:
                pass
        for stream in files:
            stream.close()
        lock.close()
        save_json(out / "summary.json", {"state": result, "measurements": count,
                  "fresh_measurements": fresh_count,
                  "one_second_counts": pairs.sequence, "raw_bins_discarded": pairs.discarded,
                  "serial_number": serial, "elapsed_s": time.monotonic() - started,
                  "hardware_test": device_factory is None,
                  "dose_conversion_verified": False})
        print(f"Fim: {result}; {count} leituras. Arquivos em {out}", flush=True)
        for sig, handler in previous_signals.items():
            signal.signal(sig, handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="Nova pasta exclusiva desta sessão")
    parser.add_argument("--serial", default=None)
    parser.add_argument("--require-counts", action="store_true", help="Falha se não houver RawData para o CEIA")
    parser.add_argument("--seconds", type=float, default=60, help="0 = contínuo")
    parser.add_argument("--poll", type=float, default=0.25)
    parser.add_argument("--no-data-timeout", type=float, default=20)
    parser.add_argument("--spectrum-interval", type=float, default=15, help="0 desabilita")
    parser.add_argument("--dose-scale", type=float, default=10000.0)
    args = parser.parse_args()
    values = [args.seconds, args.poll, args.no_data_timeout,
              args.spectrum_interval, args.dose_scale]
    if not all(math.isfinite(v) for v in values) or args.seconds < 0 or args.poll < 0.05 \
            or args.no_data_timeout <= 0 or args.spectrum_interval < 0 or args.dose_scale <= 0:
        parser.error("Parâmetros de tempo/escala inválidos")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
