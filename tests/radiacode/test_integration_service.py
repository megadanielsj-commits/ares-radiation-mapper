"""Contract and failure checks; simulated/replayed input is never a hardware pass."""

import asyncio
import importlib.util
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from radiacode import RawData

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools/radiacode_usb" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


counts, service = load("counts"), load("service")


def row(sequence=1, session="SOFTWARE-TEST", **overrides):
    value = dict(
        schema_version="ares-radiacode-counts-1",
        cps=12,
        exposure_s=1.0,
        timing_quality="live_receipt",
        received_monotonic_ns=time.monotonic_ns(),
        received_utc_ns=time.time_ns(),
        session_id=session,
        sequence=sequence,
        serial_number="REPLAY-NOT-HARDWARE",
        time_basis="host_receipt_of_second_half_bin",
        dose_rate_uSv_h=0.12,
        dose_rate_received_monotonic_ns=time.monotonic_ns(),
        dose_rate_received_utc_ns=time.time_ns(),
        configured_dose_unit="Sv",
    )
    value.update(overrides)
    return value


def test_recorded_raw_bins_make_real_integer_counts():
    pairs = counts.PairRawData()
    rows = [
        json.loads(line)
        for line in (ROOT / "tests/radiacode/fixtures/real_raw_excerpt.jsonl")
        .read_text()
        .splitlines()
    ]
    output = []
    for envelope in rows:
        data = envelope["record"]
        count = pairs.add(
            RawData(datetime.fromisoformat(data["dt"]), data["count_rate"], data["dose_rate"]),
            time.time_ns(),
            time.monotonic_ns(),
            "REPLAY",
            "REPLAY",
        )
        if count:
            output.append(count["cps"])
    expected = [
        int((rows[i]["record"]["count_rate"] + rows[i + 1]["record"]["count_rate"]) / 2)
        for i in range(0, len(rows), 2)
    ]
    assert output == expected
    assert len(output) == 8 and pairs.discarded == 0
    assert all(isinstance(cps, int) for cps in output)


def test_gaps_duplicates_and_non_integral_raw_rates_are_not_paired():
    pairs = counts.PairRawData()
    t = datetime.now()

    def add(offset, cps=20):
        return pairs.add(
            RawData(t + timedelta(seconds=offset), cps, 0),
            time.time_ns(),
            time.monotonic_ns(),
            "test",
            "test",
        )

    assert add(0) is None
    assert add(0) is None
    assert add(0.5) is None
    assert add(1)["cps"] == 20
    assert add(2.5) is None
    assert add(3, 21) is None  # half-second count must be integral
    assert add(3.5) is None
    assert add(4)["cps"] == 20
    assert pairs.discarded >= 2


def test_bridge_rejects_old_repeated_or_batched_counts_and_recovers_session(tmp_path):
    bridge = service.Bridge(tmp_path)
    assert bridge.accept(row())
    assert not bridge.accept(row())
    assert not bridge.accept(row(2, timing_quality="batched_uncertain"))
    assert not bridge.accept(row(2, received_monotonic_ns=time.monotonic_ns() - 4_000_000_000))
    assert not bridge.accept(row(2, received_utc_ns=time.time_ns() + 20_000_000_000))
    assert not bridge.accept(row(2, cps=12.4))
    bridge.last_received_ns -= 4_000_000_000
    bridge.check_freshness()
    assert bridge.device["estado"] == "desconectado" and bridge.latest is None
    assert bridge.accept(row(1, session="NEW-SESSION"))
    assert bridge.device["estado"] == "conectado" and "NEW-SESSION" in bridge.device["id"]
    assert bridge.latest["dados"]["dose_usv"] is None
    assert bridge.latest["dados"]["cpm"] == 720


def test_slow_subscriber_has_bounded_queue_and_never_blocks_recorder(tmp_path):
    bridge = service.Bridge(tmp_path)
    queue = bridge.subscribe()
    for i in range(1, 1001):
        assert bridge.accept(row(i))
    assert queue.qsize() == 4 and bridge.published == 1000
    assert queue.get_nowait()["dados"]["sequence"] == 997
    assert bridge.dropped_for_slow_clients > 990


@pytest.mark.parametrize("missing", [False, True])
def test_fresh_counts_cannot_make_old_or_undated_dose_fresh(tmp_path, missing):
    bridge = service.Bridge(tmp_path)
    value = row(dose_rate_received_monotonic_ns=time.monotonic_ns() - 5_000_000_000,
                dose_rate_received_utc_ns=time.time_ns() - 5_000_000_000)
    if missing:
        value.pop("dose_rate_received_monotonic_ns")
        value.pop("dose_rate_received_utc_ns")
    assert bridge.accept(value)
    assert bridge.latest["dados"]["cps"] == 12
    assert bridge.latest["dados"]["dr_usvh"] is None
    assert bridge.accept(row(2))
    assert bridge.latest["dados"]["dr_usvh"] == .12


@pytest.mark.parametrize("unit", ["R", None])
def test_roentgen_or_unknown_unit_keeps_counts_without_mislabeling_dose(tmp_path, unit):
    bridge = service.Bridge(tmp_path)
    assert bridge.accept(row(configured_dose_unit=unit))
    assert bridge.latest["dados"]["cps"] == 12
    assert bridge.latest["dados"]["dr_usvh"] is None
    assert bridge.accept(row(2))
    assert bridge.latest["dados"]["dr_usvh"] == .12


@pytest.mark.asyncio
async def test_follower_waits_for_complete_line_and_handles_new_session(tmp_path):
    bridge = service.Bridge(tmp_path)
    bridge.identity = tmp_path / "first"
    bridge.identity.mkdir()
    path = bridge.identity / "counts_1s.jsonl"
    content = json.dumps(row())
    path.write_text(content)
    task = asyncio.create_task(bridge.follow())
    try:
        await asyncio.sleep(0.12)
        assert bridge.published == 0
        with path.open("a") as stream:
            stream.write("\n")
        await asyncio.sleep(0.12)
        assert bridge.published == 1
        bridge.identity = tmp_path / "second"
        bridge.offset = 0
        bridge.identity.mkdir()
        (bridge.identity / "counts_1s.jsonl").write_text(
            json.dumps(row(1, session="SECOND")) + "\n"
        )
        await asyncio.sleep(0.12)
        assert bridge.published == 2 and bridge.session == "SECOND"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_ws_matches_ws_contract_without_cached_reading(tmp_path):
    bridge = service.Bridge(tmp_path)
    bridge.accept(row())
    app = service.create_app(bridge, manage_reader=False)
    with TestClient(app) as client:
        assert client.get("/health").json()["detector"]["modelo"] == "Radiacode 110"
        with client.websocket_connect("/ws") as ws:
            snapshot = ws.receive_json()
            assert snapshot["tipo"] == "snapshot" and snapshot["dados"][0]["estado"] == "conectado"
            # Run mutation on the server event loop, as the real file follower does.
            client.portal.call(bridge.accept, row(2))
            assert ws.receive_json()["tipo"] == "snapshot"
            message = ws.receive_json()
            assert message["tipo"] == "leitura" and message["dados"]["cps"] == 12
            assert message["dados"]["dose_usv"] is None
            assert message["dados"]["sequence"] == 2


@pytest.mark.asyncio
async def test_usb_process_exit_restarts_with_new_session_and_stop_terminates(
    monkeypatch, tmp_path
):
    bridge = service.Bridge(tmp_path, backoff_min=0.02, backoff_max=0.04)
    children, commands = [], []

    class Child:
        def __init__(self):
            self.returncode = None
            self.future = asyncio.get_running_loop().create_future()

        async def wait(self):
            return await asyncio.shield(self.future)

        def terminate(self):
            self.returncode = 0
            self.future.set_result(0)

        kill = terminate

    async def spawn(*cmd, **kwargs):
        commands.append(cmd)
        child = Child()
        children.append(child)
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    await bridge.start()
    try:
        await asyncio.sleep(0.05)
        bridge.accept(row())
        children[0].returncode = 1
        children[0].future.set_result(1)
        await asyncio.sleep(0.07)
        assert len(children) == 2 and bridge.device["estado"] == "desconectado"
        outputs = [cmd[cmd.index("--output") + 1] for cmd in commands]
        assert outputs[0] != outputs[1] and "--require-counts" in commands[0]
    finally:
        await bridge.stop()
    assert children[-1].returncode == 0
