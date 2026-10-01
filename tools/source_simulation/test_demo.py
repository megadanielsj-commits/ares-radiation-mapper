"""Integration checks for the restored original simulation entry point."""
import importlib.util
from pathlib import Path
import time
import csv

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('classic_simulation', Path(__file__).with_name('server.py'))
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


def test_original_dashboard_is_served_without_a_projection_adapter(tmp_path):
    with TestClient(server.create_app(tmp_path)) as client:
        response = client.get('/')
        text = response.text
        assert response.status_code == 200
        assert (ROOT/'src/ares_mapper/web/static/styles.css').read_text() in text
        assert (ROOT/'src/ares_mapper/web/static/app.js').read_text() in text
        assert 'Taxa da fonte a 1 metro' in text
        assert 'GRADIENTE ESTIMADO · ESCALA LOGARÍTMICA DA MISSÃO' in text
        assert '<b>mSv/h</b>' in text
        assert 'simulation/field.js' not in text and 'simulation/adapter.js' not in text
        assert client.get('/simulation/field.js').status_code == 404
        assert client.get('/api/v1/health').status_code == 200
        config = client.get('/api/v1/scenario').json()
        assert config['pose']['provider'] == 'manual_sim'
        assert config['detectors'][0]['source_type'] == 'simulated'
        assert config['mapping']['global_model_stable_updates'] == 5
        assert config['dashboard']['scale_mode'] == 'log_fixed'


def test_original_start_control_and_export_run_together(tmp_path):
    app = server.create_app(tmp_path)
    controller = app.state.controller
    controller.scenario.mission.duration_s = 60
    controller.scenario.mission.simulation_speed = 4
    with TestClient(app) as client:
        response = client.post('/api/v1/simulation/start', json={
            'x_m': 4.0, 'y_m': 3.0, 'dose_rate_at_1m_uSv_h': 8.0})
        assert response.status_code == 200
        assert client.post('/api/v1/mission/control', json={
            'linear_m_s': .45, 'yaw_rate_rad_s': 0}).status_code == 200
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            status = client.get('/api/v1/status').json()
            if status['counts']['mapped'] >= 3:
                break
            time.sleep(.04)
        assert status['counts']['mapped'] >= 3
        assert client.post('/api/v1/mission/stop').status_code == 200
        assert controller.mission_directory is not None
        with (controller.mission_directory/'exports/mapped_samples.csv').open() as f:
            rows = list(csv.DictReader(f))
        assert len(rows) >= 3
        assert any(float(row['base_x_m']) > 2 for row in rows)
        assert all(float(row['dose_rate_uSv_h_raw']) > 0 for row in rows)
        assert controller.latest_map.sample_count >= 3
        assert controller.latest_map.metrics['reconstruction_mode'] == 'measured_local'
        assert controller.latest_map.source_estimate is None
        assert (controller.mission_directory/'mission.json').exists()


def test_insufficient_observations_do_not_create_a_distant_peak(tmp_path):
    from ares_mapper.mapping.service import MapService
    from ares_mapper.domain.models import MappedSample
    from ares_mapper.domain.enums import MappingQuality, Quality, SyncMethod
    config = server.create_app(tmp_path).state.controller.scenario
    service = MapService('short-trajectory', config.world, config.mapping,
        inference=config.inference, grid_config=config.grid,
        residual_config=config.residual, detectors=config.detectors)
    service.add_sample(MappedSample(mission_id='short-trajectory', mapped_sequence=1,
        radiation_sequence=1, sensor_id=config.detectors[0].sensor_id,
        time_domain_id='sim:short-trajectory', effective_measurement_time_ns=0,
        frame_id='world', base_x_m=2, base_y_m=2, base_z_m=.32,
        sensor_x_m=2, sensor_y_m=2, sensor_z_m=.57, sensor_yaw_rad=0,
        dose_rate_uSv_h_raw=100, dose_rate_uSv_h_filtered=100,
        sync_method=SyncMethod.EXACT, max_pose_gap_ms=0, sync_error_estimate_ms=0,
        pose_quality=Quality.VALID, radiation_quality=Quality.VALID,
        mapping_quality=MappingQuality.VALID))
    prediction = service.predict(0)
    assert prediction.metrics['reconstruction_mode'] == 'measured_local'
    assert prediction.source_estimate is None
    finite = [value for value in prediction.values_row_major if value is not None]
    assert finite and max(finite) <= 100
    nx = len(prediction.x_coordinates_m)
    for row, y in enumerate(prediction.y_coordinates_m):
        for column, x in enumerate(prediction.x_coordinates_m):
            if ((x-2)**2+(y-2)**2)**.5 > 1.0:
                assert prediction.values_row_major[row*nx+column] is None
