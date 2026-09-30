"""Software-only tests: no real detector is claimed or required."""
import argparse
import asyncio
import importlib.util
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from radiacode import RareData, RawData, RealTimeData
from radiacode.types import Spectrum

from ares_mapper.config import ScenarioConfig
from ares_mapper.core.mission_controller import MissionController
from ares_mapper.domain.models import RadiationSample
from ares_mapper.mapping.exposure import recover_cumulative_gap

ROOT = Path(__file__).resolve().parents[2]


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools/radiacode_usb" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


reader = load_tool("reader")
launcher = load_tool("launch")


class FakeDevice:
    """Only injectable from Python tests; never a fallback in user commands."""
    def __init__(self, serial_number=None):
        self.closed = False
        self.n = 0

    def serial_number(self):
        return "SOFTWARE-TEST-NOT-HARDWARE"

    def fw_version(self):
        return ((4, 0, "test"), (4, 14, "test"))

    def configuration(self):
        return "SpecFormatVersion=0"

    def energy_calib(self):
        return [0., 3., 0.]

    def get_alarm_limits(self):
        return {"dose_unit": "Sv"}

    def data_buf(self):
        self.n += 1
        return [RareData(datetime.now(), 100, 0.001, 25.5, 80, 0),
                RealTimeData(datetime.now(), 7.25, 12, 0.000012, 10, 0, 0)]

    def spectrum(self):
        return Spectrum(timedelta(seconds=2), 0., 3., 0., [1, 2, 3])

    def close(self):
        self.closed = True


def options(path):
    return argparse.Namespace(output=path, serial=None, seconds=.2, poll=.02,
                              no_data_timeout=.1, spectrum_interval=.05, dose_scale=10000.)


def test_recorder_retains_raw_units_fractional_cps_and_spectrum(tmp_path):
    assert reader.run(options(tmp_path / "run"), FakeDevice) == 0
    rows = [json.loads(x) for x in (tmp_path / "run/readings.jsonl").read_text().splitlines()]
    assert len(rows) >= 2
    assert rows[0]["dose_rate_uSv_h"] == pytest.approx(.12)
    assert rows[0]["dose_rate_raw"] == .000012
    assert rows[0]["cps"] == 7.25
    assert rows[0]["cpm_derived"] == 435.
    assert rows[0]["cumulative_dose_uSv"] is None
    assert rows[0]["cumulative_dose_raw"] == .001
    assert not rows[0]["dose_conversion_verified"]
    spectra = [json.loads(x) for x in (tmp_path / "run/spectra.jsonl").read_text().splitlines()]
    assert spectra[0]["counts"] == [1, 2, 3]
    assert spectra[0]["energy_keV"] == [0, 3, 6]
    assert json.loads((tmp_path / "run/summary.json").read_text())["hardware_test"] is False


def test_no_data_and_disconnect_never_report_success(tmp_path):
    class Empty(FakeDevice):
        def data_buf(self):
            return []
    assert reader.run(options(tmp_path / "empty"), Empty) == 1
    summary = json.loads((tmp_path / "empty/summary.json").read_text())
    assert summary["state"] == "error" and summary["measurements"] == 0

    class Unplugged(FakeDevice):
        def data_buf(self):
            raise OSError("device disconnected")
    assert reader.run(options(tmp_path / "unplugged"), Unplugged) == 1
    assert "device disconnected" in (tmp_path / "unplugged/error.txt").read_text()


def test_repeated_buffered_measurement_cannot_mask_stalled_detector(tmp_path):
    class RepeatsOldReading(FakeDevice):
        def __init__(self, serial_number=None):
            super().__init__(serial_number)
            now = datetime.now()
            self.old = [RealTimeData(now, 7.25, 12, .000012, 10, 0, 0),
                        RealTimeData(now + timedelta(seconds=1), 8.25, 12, .000013, 10, 0, 0)]

        def data_buf(self):
            return self.old

    settings = options(tmp_path / "stalled")
    settings.seconds = .3
    settings.no_data_timeout = .07
    assert reader.run(settings, RepeatsOldReading) == 1
    summary = json.loads((tmp_path / "stalled/summary.json").read_text())
    assert summary["state"] == "error"
    assert summary["fresh_measurements"] == 2
    rows = [json.loads(x) for x in (tmp_path / "stalled/readings.jsonl").read_text().splitlines()]
    assert len(rows) >= 4 and rows[2]["is_duplicate"] and rows[3]["is_duplicate"]
    assert "Sem RealTimeData nova" in (tmp_path / "stalled/error.txt").read_text()


@pytest.mark.asyncio
async def test_live_file_drives_virtual_robot_and_stops_cleanly(tmp_path):
    readings = tmp_path / "readings.jsonl"
    readings.touch()
    config = ScenarioConfig.model_validate(launcher.make_scenario(readings, tmp_path, 30))
    config.inference.render_particles = 32
    config.inference.particles = 64
    controller = MissionController(config)
    await controller.start()
    start_x = config.trajectory.start_m[0]
    await controller.manual_control(.4, 0.)
    with readings.open("a") as stream:
        for i in range(1, 5):
            await asyncio.sleep(.3)
            row = reader.measurement(RealTimeData(datetime.now(), 7.25, 12, .000012, 10, 0, 0),
                                     i, time.time_ns(), time.monotonic_ns(), scale=10000,
                                     session_id="test", serial="TEST", status={})
            reader.json_line(stream, row)
        await asyncio.sleep(.7)
    assert controller.latest_radiation.cps == 7.25
    assert controller.latest_radiation.cumulative_dose_uSv is None
    assert controller.latest_pose.x_m > start_x
    assert controller.status()["counts"]["radiation"] == 4
    assert controller.status()["counts"]["mapped"] >= 1
    with pytest.raises(ValueError):
        await controller.pause()
    with pytest.raises(ValueError):
        await controller.set_speed(2)
    await controller.stop()
    await asyncio.wait_for(controller.wait_until_complete(), 15)


@pytest.mark.asyncio
async def test_partial_lines_and_slow_consumer_preserve_receipt_time(tmp_path):
    from ares_mapper.adapters.radiacode_jsonl import RadiacodeJsonlSource
    from ares_mapper.config import DetectorConfig
    from ares_mapper.core.clock import SimulationClock
    from ares_mapper.domain.models import RunContext
    path = tmp_path / "readings.jsonl"
    path.touch()
    clock = SimulationClock()
    source = RadiacodeJsonlSource(
        DetectorConfig(source_type="radiacode_jsonl", live_jsonl_path=path),
        clock,
        30,
    )
    await source.start(RunContext(mission_id="test", mode="test", time_domain_id="test", seed=1,
                                  started_utc_ns=time.time_ns()))
    await clock.resume()
    await asyncio.sleep(.1)
    receipt = time.monotonic_ns()
    row = reader.measurement(
        RealTimeData(datetime.now(), 7.25, 12, .000012, 10, 0, 0),
        1, time.time_ns(), receipt, scale=10000, session_id="test", serial="TEST", status={},
    )
    iterator = source.samples()
    task = asyncio.create_task(anext(iterator))
    with path.open("a") as stream:
        stream.write(json.dumps(row))
        stream.flush()
        await asyncio.sleep(.15)
        assert not task.done()
        stream.write("\n")
        stream.flush()
        sample = await asyncio.wait_for(task, 1)
    assert sample.received_monotonic_ns == receipt
    assert abs(sample.timeline_time_ns - 100_000_000) < 60_000_000
    await source.stop()
    await iterator.aclose()
    await clock.stop()


def test_missing_accumulated_dose_does_not_become_zero_or_gap_evidence():
    common = dict(mission_id="test", sensor_id="test", time_domain_id="test",
                  received_utc_ns=0, received_monotonic_ns=0, dose_rate_uSv_h=.12,
                  cumulative_dose_uSv=None)
    first = RadiationSample(
        **common, sequence=1, timeline_time_ns=1, effective_measurement_time_ns=1
    )
    last = RadiationSample(**common, sequence=10, timeline_time_ns=10_000_000_000,
                           effective_measurement_time_ns=10_000_000_000)
    assert recover_cumulative_gap(first, last, .01) is None


def test_recorder_keeps_smoothed_cps_separate_from_raw_counts(tmp_path):
    class WithRaw(FakeDevice):
        def __init__(self, serial_number=None):
            super().__init__(serial_number)
            self.origin = datetime.now()

        def data_buf(self):
            records = super().data_buf()
            dt = self.origin + timedelta(seconds=self.n)
            return records + [
                RawData(dt, 10, 0.000012),
                RawData(dt + timedelta(seconds=0.5), 14, 0.000012),
            ]

    settings = options(tmp_path / "raw-counts")
    settings.require_counts = True
    assert reader.run(settings, WithRaw) == 0
    rows = [
        json.loads(line)
        for line in (tmp_path / "raw-counts/counts_1s.jsonl").read_text().splitlines()
    ]
    assert len(rows) >= 2
    assert rows[0]["cps"] == 12 and rows[0]["exposure_s"] == 1
    assert rows[0]["timing_quality"] == "live_receipt"
    assert rows[0]["received_utc_ns"] > 0 and rows[0]["received_monotonic_ns"] > 0
    summary = json.loads((tmp_path / "raw-counts/summary.json").read_text())
    assert summary["one_second_counts"] == len(rows) and not summary["hardware_test"]
