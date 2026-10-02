"""Protocol dose channel across the recorder/WS boundary; no physical USB claim."""
import argparse
import asyncio
import csv
import importlib.util
import io
import json
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from radiacode import RawData, RealTimeData
from radiacode.types import AlarmLimits

from tools.operator_console.server import create_app

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools/radiacode_usb" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


reader, service = load("reader"), load("service")

# Channel definition matches configuration() in the recorded Radiacode 110 runs.
CONFIGURATION = '''[DataStructure]
[[GRP_RealTimeData]]
Id=0
[[[CHN_CountRate]]]
Unit=" cps| имп/с"
[[[CHN_DoseRate]]]
Unit=" R/h| Р/ч"
ScaledUnit=1
[[[CHN_DoseRateErr]]]
Unit=%
[[GRP_RareData]]
[[[CHN_Dose]]]
Unit=" R| Р"
'''
RAW_RATE = 1.2651909855776466e-05
REPORTED_RATE = RAW_RATE * 10000


class ProtocolDoseDevice:
    """SDK-shaped records with the display-unit R found in the user's archive."""
    display_unit = "R"
    configuration_text = CONFIGURATION

    def __init__(self, serial_number=None):
        self.n = 0
        self.origin = datetime.now()

    def serial_number(self):
        return "PROTOCOL-DOUBLE-NOT-HARDWARE"

    def fw_version(self):
        return ((4, 0, "test"), (4, 14, "test"))

    def configuration(self):
        return self.configuration_text

    def energy_calib(self):
        return [0, 3, 0]

    def get_alarm_limits(self):
        if self.display_unit is None:
            raise OSError("Alarm unit query unavailable in this protocol double")
        return AlarmLimits(2020, 2020, "cps", 114, 114, 999, 999, self.display_unit)

    def data_buf(self):
        self.n += 1
        dt = self.origin + timedelta(seconds=self.n)
        return [RealTimeData(dt, 7.25123456789, 12, RAW_RATE, 10, 0, 0),
                RawData(dt, 10, RAW_RATE),
                RawData(dt + timedelta(seconds=.5), 16, RAW_RATE)]

    def close(self):
        pass


@pytest.mark.parametrize("display_unit", ["R", "Sv", None])
def test_recorder_ws_keep_reported_dose_and_fractional_precision(tmp_path, display_unit):
    class Device(ProtocolDoseDevice):
        pass

    Device.display_unit = display_unit
    output = tmp_path / "recording"
    args = argparse.Namespace(output=output, serial=None, seconds=.10, poll=.02,
                              no_data_timeout=.1, spectrum_interval=0, dose_scale=10000,
                              require_counts=True)
    assert reader.run(args, Device) == 0
    session = json.loads((output / "session.json").read_text())
    assert session["configured_dose_unit"] == display_unit
    if display_unit is not None:
        assert session["get_alarm_limits"]["dose_unit"] == display_unit
    else:
        assert "get_alarm_limits_error" in session
    paired = [json.loads(line) for line in (output / "counts_1s.jsonl").read_text().splitlines()]
    assert paired[0]["dose_rate_raw"] == RAW_RATE
    assert paired[0]["dose_rate_uSv_h"] == REPORTED_RATE
    assert paired[0]["cps"] == 13  # exact independent raw bins, not rounded smoothed CPS
    readings = [json.loads(line) for line in (output / "readings.jsonl").read_text().splitlines()]
    assert readings[0]["cps"] == 7.25123456789
    with (output / "readings.csv").open() as stream:
        saved = next(csv.DictReader(stream))
    assert float(saved["dose_rate_raw"]) == RAW_RATE
    assert float(saved["dose_rate_uSv_h"]) == REPORTED_RATE
    assert float(saved["cps"]) == readings[0]["cps"]

    bridge = service.Bridge(output)
    assert bridge.accept(paired[0])
    app = service.create_app(bridge, manage_reader=False)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.receive_json()  # snapshot; no replay of old readings
        client.portal.call(bridge.accept, paired[1])
        snapshot = ws.receive_json()
        message = ws.receive_json()
    assert snapshot["tipo"] == "snapshot"
    assert message["dados"]["dr_usvh"] == REPORTED_RATE
    assert message["dados"]["cps"] == 13
    assert message["dados"]["cpm"] == 780
    assert message["dados"]["dose_rate_received_utc_ns"] == paired[1]["dose_rate_received_utc_ns"]


def test_native_dose_channel_unit_is_independent_of_alarm_unit():
    metadata = reader.dose_channel_metadata(CONFIGURATION, 10000)
    assert metadata["dose_rate_native_unit"] == "R/h"
    assert metadata["dose_rate_unit"] == "uSv/h"
    assert metadata["dose_rate_conversion_available"] is True
    assert reader.dose_channel_metadata(CONFIGURATION.replace(' R/h|', ' unknown|'), 10000)[
        "dose_rate_conversion_available"
    ] is False
    assert reader.dose_channel_metadata(CONFIGURATION, 1)["dose_rate_conversion_available"] is False


def test_unknown_channel_keeps_raw_records_and_counts_without_inventing_dose(tmp_path):
    class Device(ProtocolDoseDevice):
        configuration_text = CONFIGURATION.replace(' R/h|', ' unknown|')

    output = tmp_path / "unknown-channel"
    args = argparse.Namespace(output=output, serial=None, seconds=.10, poll=.02,
                              no_data_timeout=.1, spectrum_interval=0, dose_scale=10000,
                              require_counts=True)
    assert reader.run(args, Device) == 0
    paired = json.loads((output / "counts_1s.jsonl").read_text().splitlines()[0])
    assert paired["dose_rate_uSv_h"] is None
    assert paired["dose_rate_raw"] == RAW_RATE
    assert paired["cps"] == 13
    with (output / "readings.csv").open() as stream:
        saved = next(csv.DictReader(stream))
    assert saved["dose_rate_uSv_h"] == ""
    assert float(saved["dose_rate_raw"]) == RAW_RATE
    bridge = service.Bridge(output)
    assert bridge.accept(paired)
    assert bridge.latest["dados"]["dr_usvh"] is None
    assert bridge.latest["dados"]["cps"] == 13
    assert bridge.latest["dados"]["cpm"] == 780


@pytest.mark.parametrize("mode", ["usb_simulated_robot", "hardware"])
def test_ws_decoder_runtime_map_and_csv_preserve_the_reported_rate(tmp_path, mode):
    from ares.radiacao.radiacode import ClienteRadiacode
    from ares.simulacao.robo import RoboSimulado

    from tools.operator_console.test_console import wait_for

    output = tmp_path / "source-recording"
    args = argparse.Namespace(output=output, serial=None, seconds=.10, poll=.02,
                              no_data_timeout=.1, spectrum_interval=0, dose_scale=10000,
                              require_counts=True)
    assert reader.run(args, ProtocolDoseDevice) == 0
    template = json.loads((output / "counts_1s.jsonl").read_text().splitlines()[0])

    class ProtocolTransport:
        """Deliver newly timestamped software fixtures to the unchanged WS decoder."""
        def __init__(self):
            self.bridge = service.Bridge(output)
            self.decoder = ClienteRadiacode()
            self.sequence = 0

        def assinar(self, callback):
            self.decoder.assinar(callback)

        def estado(self):
            return self.decoder.estado()

        async def iniciar(self):
            self.decoder._conectado = True
            self.task = asyncio.create_task(self.run())

        async def encerrar(self):
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.decoder._conectado = False

        async def run(self):
            while True:
                await asyncio.sleep(.2)
                self.sequence += 1
                utc, mono = time.time_ns(), time.monotonic_ns()
                frame = dict(template, sequence=self.sequence, received_utc_ns=utc,
                             received_monotonic_ns=mono, dose_rate_received_utc_ns=utc,
                             dose_rate_received_monotonic_ns=mono)
                assert self.bridge.accept(frame)
                self.decoder._processar_evento({"tipo":"snapshot", "dados":[self.bridge.device]})
                self.decoder._processar_evento(self.bridge.latest)

    app = create_app(tmp_path / "console", {"real_robot":RoboSimulado,
                                          "real_radiation":ProtocolTransport}, manage_usb=False)
    with TestClient(app) as client:
        assert client.post("/api/console/configure", json={"mode":mode}).status_code == 200
        snapshot = wait_for(client, lambda s:s["robot"]["conectado"]
                            and s["status"]["radiation"] is not None)
        assert snapshot["status"]["radiation"]["dose_rate_uSv_h"] == REPORTED_RATE
        assert snapshot["status"]["radiation"]["cps"] == 13
        assert snapshot["status"]["radiation"]["cpm"] == 780
        assert client.post("/api/console/start", json={}).status_code == 200
        wait_for(client, lambda s:s["status"]["counts"]["mapped"] >= 3)
        assert client.post("/api/console/stop", json={}).status_code == 200
        active = app.state.console.active
        for sample in active.worker.samples:
            assert sample.dose_rate_uSv_h_raw == REPORTED_RATE
            assert sample.dose_rate_uSv_h_filtered == REPORTED_RATE
            assert sample.cps == 13 and sample.cpm == 780
        assert active.latest_map.exposure.cumulative_robot_path_dose_uSv == pytest.approx(
            len(active.worker.samples) * REPORTED_RATE / 3600)
        with zipfile.ZipFile(io.BytesIO(client.get("/api/console/export").content)) as package:
            rows = list(csv.DictReader(io.StringIO(package.read("amostras.csv").decode())))
            assert all(float(row["dr_usvh"]) == REPORTED_RATE for row in rows)
            assert all(int(row["cps"]) == 13 and int(row["cpm"]) == 780 for row in rows)
            raw = json.loads(package.read("mission_raw.json"))
            assert all(row["dr_usvh"] == REPORTED_RATE for row in raw["leituras"])
            assert json.loads(package.read("map_latest.json"))["display_unit"] == "mSv/h"
