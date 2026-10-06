"""One-second acquisition cadence and configurable virtual-only motion."""
from datetime import datetime, timedelta
from types import SimpleNamespace
import time

from fastapi.testclient import TestClient
import pytest

from tools.operator_console.runtime import (
    Setup, scenario, LiveController, ConsoleBus, RADIACODE_READING_PERIOD_S,
)
from tools.operator_console.server import create_app
from tools.operator_console.test_console import FACTORIES, wait_for
from tools.radiacode_usb.counts import PairRawData


def test_simulators_use_the_usb_count_window_not_the_usb_polling_period(tmp_path):
    pairs = PairRawData()
    rows = []
    for n in range(4):
        record = SimpleNamespace(dt=datetime(2026, 10, 6)+timedelta(seconds=n*.5), count_rate=2)
        row = pairs.add(record, 1_000_000_000+n*500_000_000, n*500_000_000, 'test', 'serial')
        if row is not None:
            rows.append(row)
    assert len(rows) == 2
    assert rows[0]['exposure_s'] == RADIACODE_READING_PERIOD_S == 1
    assert (rows[1]['received_utc_ns']-rows[0]['received_utc_ns'])/1e9 == RADIACODE_READING_PERIOD_S
    cfg = scenario(tmp_path, Setup(simulated_robot_speed_m_s=1.2))
    assert cfg.mission.simulation_speed == 1
    assert cfg.detectors[0].publish_rate_hz == 1 / rows[0]['exposure_s']
    assert cfg.detectors[0].jitter_ms_std == 0
    setup = Setup(mode='robot_simulated_source')
    live = LiveController(scenario(tmp_path, setup), setup, tmp_path, ConsoleBus(), FACTORIES)
    assert live.orq.radiacao._periodo_s == RADIACODE_READING_PERIOD_S


@pytest.mark.parametrize('speed', [.1, 1.2])
def test_virtual_speed_reaches_the_trajectory_without_accelerating_acquisition(tmp_path, speed):
    app = create_app(tmp_path, manage_usb=False)
    with TestClient(app) as client:
        response = client.post('/api/console/configure', json={'mode':'simulation', 'simulated_robot_speed_m_s':speed})
        assert response.status_code == 200
        assert response.json()['setup']['simulated_robot_speed_m_s'] == speed
        assert app.state.console.active.scenario.trajectory.speed_m_s == speed
        assert client.post('/api/console/start', json={}).status_code == 200
        assert app.state.console.active.clock.speed == 1
        assert client.post('/api/console/enable-control', json={'client':'speed-test'}).status_code == 200
        # The backend enforces the configured limit, even for an oversized command.
        assert client.post('/api/console/control', json={'client':'speed-test','linear_m_s':20}).status_code == 200
        active = app.state.console.active
        assert active._manual_command['linear_m_s'] == speed
        now = active.current_time_ns/1e9
        pose = active.trajectory.pose_at(now)
        assert abs(pose.vx_m_s) == pytest.approx(speed)
        assert client.post('/api/console/control', json={'client':'speed-test','linear_m_s':-20}).status_code == 200
        assert active._manual_command['linear_m_s'] == -speed
        assert client.post('/api/console/brake', json={}).status_code == 200
        assert active._manual_command['linear_m_s'] == 0
        assert client.post('/api/console/configure', json={'simulated_robot_speed_m_s':.8}).status_code == 409


def test_simulation_emits_separate_one_second_readings_with_original_precision(tmp_path):
    app = create_app(tmp_path, manage_usb=False)
    samples = []
    with TestClient(app) as client:
        bus = app.state.console.event_bus
        publish = bus.publish

        async def capture(kind, payload):
            if kind == 'radiation':
                samples.append(payload.model_dump() if hasattr(payload, 'model_dump') else payload)
            await publish(kind, payload)

        bus.publish = capture
        assert client.post('/api/console/start', json={}).status_code == 200
        deadline = time.monotonic()+12
        while len(samples) < 3:
            assert time.monotonic() < deadline
            time.sleep(.05)
        assert client.post('/api/console/stop', json={}).status_code == 200
        assert all(s['integration_time_s'] == 1 for s in samples)
        assert all(b['timeline_time_ns']-a['timeline_time_ns'] == 1_000_000_000
                   for a, b in zip(samples, samples[1:]))
        assert all(s['dose_rate_uSv_h'] is not None and s['cps'] is not None for s in samples)
        assert samples[0]['dose_rate_uSv_h'] != samples[0]['cps']
        print('Observed simulated receipt intervals:',
              [(b['received_monotonic_ns']-a['received_monotonic_ns'])/1e9
               for a, b in zip(samples, samples[1:])])


@pytest.mark.parametrize('speed', [0, -.1, 2.1, 'NaN', 'Infinity'])
def test_invalid_virtual_speed_is_rejected_without_reconfiguring(tmp_path, speed):
    app = create_app(tmp_path, manage_usb=False)
    with TestClient(app) as client:
        assert client.post('/api/console/configure', json={'simulated_robot_speed_m_s':speed}).status_code == 422
        assert app.state.console.setup.simulated_robot_speed_m_s == .45


def test_full_simulation_speed_does_not_raise_werik_teleop_limits(tmp_path):
    app = create_app(tmp_path, FACTORIES, manage_usb=False)
    with TestClient(app) as client:
        response = client.post('/api/console/configure', json={'mode':'usb_simulated_robot','simulated_robot_speed_m_s':2})
        assert response.status_code == 200
        wait_for(client, lambda s:s['status']['pose'] is not None)
        teleop = app.state.console.active.teleop
        teleop.definir(2, 0, 0)
        assert teleop._vx == .45
