from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from ares_mapper.config import ScenarioConfig, load_scenario
from ares_mapper.core.mission_controller import MissionController
from ares_mapper.domain.enums import MissionState


@pytest.mark.asyncio
async def test_real_time_manual_simulation_stays_running_and_moves(
    short_scenario: ScenarioConfig,
) -> None:
    config = short_scenario.model_copy(deep=True)
    config.mission.duration_s = 5.0
    config.mission.simulation_speed = 1.0
    controller = MissionController(config)

    await controller.start()
    await asyncio.sleep(0.2)
    assert controller.state == MissionState.RUNNING
    assert controller.latest_pose is not None
    initial_x = controller.latest_pose.x_m

    await controller.manual_control(linear_m_s=0.45, yaw_rate_rad_s=0.0)
    await asyncio.sleep(0.5)

    assert controller.state == MissionState.RUNNING
    assert controller.latest_pose is not None
    assert controller.latest_pose.x_m > initial_x + 0.1
    assert controller.alerts == []
    await controller.stop("test_complete")


@pytest.mark.asyncio
async def test_complete_mission_creates_replayable_artifacts(
    short_scenario: ScenarioConfig,
) -> None:
    controller = MissionController(short_scenario)
    mission_id = await controller.start()
    await controller.wait_until_complete()

    assert controller.state == MissionState.COMPLETED
    assert controller.status()["counts"]["radiation"] == 2
    assert controller.status()["counts"]["mapped"] == 2
    assert controller.mission_directory is not None
    assert (controller.mission_directory / "mission.sqlite").exists()
    assert (controller.mission_directory / "exports" / "map_latest.png").exists()
    assert (controller.mission_directory / "exports" / "mapped_samples.csv").exists()

    replay = await MissionController.from_mission(controller.mission_directory)
    assert replay.mission_id == mission_id
    assert replay.state == MissionState.COMPLETED
    assert replay.latest_map is not None
    assert replay.latest_map.sample_count == 2
    assert replay.latest_posterior is not None
    assert controller.latest_posterior is not None
    assert (
        replay.latest_posterior.posterior_mean_x_y == controller.latest_posterior.posterior_mean_x_y
    )
    assert replay.latest_map.values_row_major == controller.latest_map.values_row_major  # type: ignore[union-attr]
    assert controller.latest_map is not None
    assert controller.latest_map.exposure is not None
    assert controller.map_service is not None
    expected_path_dose = sum(
        sample.dose_rate_uSv_h_filtered * float(sample.integration_time_s or 1.0) / 3600.0
        for sample in controller.map_service.samples
    )
    assert controller.latest_map.exposure.cumulative_robot_path_dose_uSv == pytest.approx(
        expected_path_dose
    )


@pytest.mark.asyncio
async def test_same_seed_reproduces_radiation_values(
    short_scenario: ScenarioConfig,
    tmp_path: Path,
) -> None:
    first = MissionController(short_scenario.model_copy(deep=True))
    await first.start()
    await first.wait_until_complete()
    first_values = [
        item.dose_rate_uSv_h_raw
        for item in first.map_service.samples  # type: ignore[union-attr]
    ]

    second_config = short_scenario.model_copy(deep=True)
    second_config.application.data_directory = tmp_path / "second"
    second = MissionController(second_config)
    await second.start()
    await second.wait_until_complete()
    second_values = [
        item.dose_rate_uSv_h_raw
        for item in second.map_service.samples  # type: ignore[union-attr]
    ]
    assert first_values == second_values


@pytest.mark.asyncio
async def test_pause_step_and_resume(short_scenario: ScenarioConfig) -> None:
    config = short_scenario.model_copy(deep=True)
    config.mission.duration_s = 1.0
    config.mission.simulation_speed = 1.0
    controller = MissionController(config)
    await controller.start()
    await controller.pause()
    before = controller.current_time_ns
    stepped = await controller.step(0.2)
    assert controller.state == MissionState.PAUSED
    assert stepped >= before + 200_000_000
    await controller.set_speed(200)
    await controller.resume()
    await controller.wait_until_complete()
    assert controller.state == MissionState.COMPLETED


@pytest.mark.asyncio
async def test_real_fs5000_csv_can_drive_virtual_map(tmp_path: Path) -> None:
    config = load_scenario("config/scenarios/fs5000_replay.yaml")
    config.mission.duration_s = 3.0
    config.mission.simulation_speed = 200.0
    config.application.data_directory = tmp_path / "csv-replay"
    config.mapping.grid_resolution_m = 0.25
    controller = MissionController(config)
    await controller.start()
    await controller.wait_until_complete()
    assert controller.status()["counts"]["radiation"] == 3
    assert controller.status()["counts"]["mapped"] == 3
    assert controller.latest_map is not None
    assert "rmse_uSv_h" not in controller.latest_map.metrics


@pytest.mark.asyncio
async def test_two_detectors_share_one_posterior_without_channel_duplication(
    tmp_path: Path,
) -> None:
    config = load_scenario("config/scenarios/two_detectors.yaml")
    config.mission.duration_s = 2.0
    config.mission.simulation_speed = 200.0
    config.application.data_directory = tmp_path / "two-detectors"
    controller = MissionController(config)
    await controller.start()
    await controller.wait_until_complete()
    assert controller.state == MissionState.COMPLETED
    assert controller.status()["counts"]["radiation"] == 4
    assert controller.status()["counts"]["mapped"] == 4
    assert controller.latest_posterior is not None
    assert controller.latest_posterior.update_sequence == 4
