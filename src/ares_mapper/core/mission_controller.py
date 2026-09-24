"""Mission lifecycle and end-to-end pipeline orchestration."""

from __future__ import annotations

import asyncio
import json
import re
import time
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ares_mapper.adapters.fs5000.source import FS5000SerialSource
from ares_mapper.adapters.radiacode_jsonl import RadiacodeJsonlSource
from ares_mapper.adapters.unitree.ros2_tf_source import Ros2TfPoseSource
from ares_mapper.adapters.unitree.sdk2_source import UnitreeSdk2PoseSource
from ares_mapper.adapters.unitree.sport_commander import Go2SportCommander
from ares_mapper.config import (
    IOE_INVESTIGATION_EQUIVALENT_RATE_USV_H,
    IOE_LIMIT_EQUIVALENT_RATE_USV_H,
    IOE_MAXIMUM_EQUIVALENT_RATE_USV_H,
    IOE_RECORDING_EQUIVALENT_RATE_USV_H,
    IOE_REFERENCE_HOURS_PER_YEAR,
    MAX_SIMULATION_SOURCE_STRENGTH_USV_H,
    PUBLIC_CONTINUOUS_REFERENCE_RATE_USV_H,
    PositionKeyframeConfig,
    ScenarioConfig,
    StrengthKeyframeConfig,
    load_scenario,
)
from ares_mapper.core.clock import SimulationClock
from ares_mapper.core.event_bus import EventBus
from ares_mapper.core.synchronizer import TemporalSynchronizer
from ares_mapper.domain.enums import (
    EvidenceKind,
    MissionState,
    ObservationMode,
    Quality,
)
from ares_mapper.domain.models import (
    MappedSample,
    MapPrediction,
    ObservationWindow,
    PoseSample,
    RadiationSample,
    RunContext,
    ScenarioEvent,
    SourcePosterior,
    TelemetrySnapshot,
)
from ares_mapper.mapping.exposure import recover_cumulative_gap
from ares_mapper.mapping.service import MapService
from ares_mapper.providers.base import PoseSource, RadiationSource
from ares_mapper.radiological_scale import mission_scale_bounds
from ares_mapper.simulation.csv_radiation_source import CsvRadiationSource
from ares_mapper.simulation.pose_coupled_radiation_source import (
    PoseCoupledSimulatedRadiationSource,
)
from ares_mapper.simulation.pose_source import SimulatedPoseSource
from ares_mapper.simulation.radiation_field import RadiationField
from ares_mapper.simulation.radiation_source import SimulatedRadiationSource
from ares_mapper.simulation.trajectory import Trajectory
from ares_mapper.storage.database import MissionStore
from ares_mapper.storage.export import MissionExporter
from ares_mapper.version import __version__


class MissionController:
    """Owns exactly one live mission or one loaded replay."""

    def __init__(self, scenario: ScenarioConfig) -> None:
        self.scenario = scenario
        self.state = MissionState.READY
        self.event_bus = EventBus()
        self.mission_id: str | None = None
        self.mission_directory: Path | None = None
        self.clock: SimulationClock | None = None
        self.store: MissionStore | None = None
        self.trajectory: Trajectory | None = None
        self.field: RadiationField | None = None
        self.map_service: MapService | None = None
        self.synchronizer: TemporalSynchronizer | None = None
        self.pose_source: PoseSource | None = None
        self.sport_commander: Go2SportCommander | None = None
        self.radiation_sources: list[RadiationSource] = []
        self.latest_pose: PoseSample | None = None
        self.latest_radiation: RadiationSample | None = None
        self.latest_mapped: MappedSample | None = None
        self.latest_map: MapPrediction | None = None
        self.latest_posterior: SourcePosterior | None = None
        self.alerts: list[str] = []
        self._runner_task: asyncio.Task[None] | None = None
        self._map_task: asyncio.Task[None] | None = None
        self._inference_task: asyncio.Task[None] | None = None
        self._map_publisher_task: asyncio.Task[None] | None = None
        self._observation_queue: asyncio.Queue[tuple[ObservationWindow, MappedSample] | None] = (
            asyncio.Queue(maxsize=256)
        )
        self._map_snapshot_queue: asyncio.Queue[MapPrediction] = asyncio.Queue(maxsize=1)
        self._stop_requested = asyncio.Event()
        self._pose_condition = asyncio.Condition()
        self._pose_finished = False
        self._finalized = False
        self._lock = asyncio.Lock()
        self._stop_reason = "duration_completed"
        self._counts = {
            "pose": 0,
            "radiation": 0,
            "mapped": 0,
            "events": 0,
            "duplicates": 0,
            "unsynchronized": 0,
            "cumulative_recovery": 0,
        }
        self._started_utc_ns: int | None = None
        self._replay_time_ns = 0
        self._last_snapshot_second = -1
        self._last_pose_publish_monotonic_ns = 0
        self._manifest: dict[str, Any] = {}
        self._manual_command = {"linear_m_s": 0.0, "yaw_rate_rad_s": 0.0}
        self._previous_radiation: dict[str, RadiationSample] = {}

    @classmethod
    async def from_mission(cls, mission_directory: str | Path) -> MissionController:
        directory = Path(mission_directory)
        scenario = load_scenario(directory / "scenario.yaml")
        controller = cls(scenario)
        database_path = directory / "mission.sqlite"
        mission_row = await MissionStore.read_mission(database_path)
        controller.mission_id = str(mission_row["mission_id"])
        controller.mission_directory = directory
        controller.state = MissionState.COMPLETED
        controller._started_utc_ns = int(mission_row["started_utc_ns"])
        controller._manifest = (
            json.loads(mission_row["manifest_json"]) if mission_row["manifest_json"] else {}
        )
        controller.field = RadiationField(scenario.world, scenario.radiation_sources)
        has_simulated_radiation_truth = all(
            detector.source_type == "simulated" for detector in scenario.detectors
        )
        controller.map_service = MapService(
            controller.mission_id,
            scenario.world,
            scenario.mapping,
            controller.field if has_simulated_radiation_truth else None,
            inference=scenario.inference,
            grid_config=scenario.grid,
            residual_config=scenario.residual,
            detectors=scenario.detectors,
            seed=scenario.mission.seed,
        )
        mapped_rows = await MissionStore.read_payloads(database_path, "mapped_samples")
        observation_rows = await MissionStore.read_payloads(database_path, "observation_windows")
        if observation_rows:
            mapped_by_sequence = {
                int(row["mapped_sequence"]): MappedSample.model_validate(row) for row in mapped_rows
            }
            for row in observation_rows:
                window = ObservationWindow.model_validate(row)
                mapped = mapped_by_sequence.get(window.observation_sequence)
                if mapped is not None:
                    controller.map_service.add_observation(window, mapped)
        else:
            for row in mapped_rows:
                controller.map_service.add_sample(MappedSample.model_validate(row))
        pose_rows = await MissionStore.read_payloads(database_path, "pose_samples")
        radiation_rows = await MissionStore.read_payloads(database_path, "radiation_samples")
        map_rows = await MissionStore.read_payloads(database_path, "map_snapshots")
        if pose_rows:
            controller.latest_pose = PoseSample.model_validate(pose_rows[-1])
        if radiation_rows:
            controller.latest_radiation = RadiationSample.model_validate(radiation_rows[-1])
        if mapped_rows:
            controller.latest_mapped = MappedSample.model_validate(mapped_rows[-1])
            controller._replay_time_ns = controller.latest_mapped.effective_measurement_time_ns
            controller.latest_map = (
                MapPrediction.model_validate(map_rows[-1])
                if map_rows
                else controller.map_service.predict(controller._replay_time_ns)
            )
            controller.latest_posterior = controller.map_service.latest_posterior
        controller._counts = {
            "pose": len(pose_rows),
            "radiation": len(radiation_rows),
            "mapped": len(mapped_rows),
            "events": len(await MissionStore.read_payloads(database_path, "scenario_events")),
            "duplicates": sum(bool(row.get("is_duplicate")) for row in radiation_rows),
            "unsynchronized": int(
                controller._manifest.get("record_counts", {}).get("unsynchronized", 0)
            ),
            "cumulative_recovery": sum(
                row.get("evidence_kind") == EvidenceKind.CUMULATIVE_RECOVERY.value
                for row in observation_rows
            ),
        }
        return controller

    async def start(self) -> str:
        async with self._lock:
            if self.state not in {MissionState.READY, MissionState.COMPLETED}:
                raise RuntimeError(f"mission cannot start from {self.state}")
            self._reset_runtime()
            self.mission_id = self._make_mission_id()
            self.mission_directory = (
                self.scenario.application.data_directory / self.mission_id
            ).resolve()
            self._started_utc_ns = time.time_ns()
            self.clock = SimulationClock(self.scenario.mission.simulation_speed)
            self.trajectory = Trajectory(
                self.scenario.trajectory,
                self.scenario.world,
                self.scenario.mission.seed,
                self.scenario.mission.duration_s,
            )
            self.field = RadiationField(self.scenario.world, self.scenario.radiation_sources)
            has_simulated_radiation_truth = all(
                detector.source_type == "simulated" for detector in self.scenario.detectors
            )
            self.map_service = MapService(
                self.mission_id,
                self.scenario.world,
                self.scenario.mapping,
                self.field if has_simulated_radiation_truth else None,
                inference=self.scenario.inference,
                grid_config=self.scenario.grid,
                residual_config=self.scenario.residual,
                detectors=self.scenario.detectors,
                seed=self.scenario.mission.seed,
            )
            transforms = {
                detector.sensor_id: detector.transform_base_sensor
                for detector in self.scenario.detectors
            }
            self.synchronizer = TemporalSynchronizer(
                self.scenario.synchronization,
                transforms,
                buffer_duration_s=self.scenario.cadence.maximum_pose_history_s,
                detectors={detector.sensor_id: detector for detector in self.scenario.detectors},
            )
            self.sport_commander = None
            if self.scenario.pose.provider in {"manual_sim", "simulated"}:
                self.pose_source = SimulatedPoseSource(
                    self.scenario.odometry,
                    self.trajectory,
                    self.clock,
                    self.scenario.mission.duration_s,
                    self.scenario.mission.seed,
                )
            elif self.scenario.pose.provider == "unitree_sportmode":
                self.pose_source = UnitreeSdk2PoseSource(
                    self.scenario.pose.network_interface,
                    self.scenario.pose.domain_id,
                    self.scenario.pose.topic,
                    config=self.scenario.pose,
                    clock=self.clock,
                )
                self.sport_commander = Go2SportCommander(
                    self.scenario.pose.network_interface,
                    self.scenario.pose.domain_id,
                )
            elif self.scenario.pose.provider == "ros_tf":
                self.pose_source = Ros2TfPoseSource(
                    self.scenario.pose.network_interface,
                    self.scenario.pose.domain_id,
                    self.scenario.pose.topic,
                    config=self.scenario.pose,
                    clock=self.clock,
                )
            else:
                raise RuntimeError(f"unsupported live pose provider: {self.scenario.pose.provider}")
            self.radiation_sources = []
            for index, detector in enumerate(self.scenario.detectors):
                if detector.source_type == "simulated":
                    if self.scenario.pose.provider in {"manual_sim", "simulated"}:
                        source: RadiationSource = SimulatedRadiationSource(
                            detector,
                            self.trajectory,
                            self.field,
                            self.clock,
                            self.scenario.mission.duration_s,
                            self.scenario.mission.seed + index * 1000,
                        )
                    else:
                        source = PoseCoupledSimulatedRadiationSource(
                            detector,
                            self.synchronizer,
                            self.field,
                            self.clock,
                            self.scenario.mission.duration_s,
                            self.scenario.mission.seed + index * 1000,
                        )
                elif detector.source_type == "csv_replay":
                    source = CsvRadiationSource(
                        detector,
                        self.clock,
                        self.scenario.mission.duration_s,
                    )
                elif detector.source_type == "radiacode_jsonl":
                    if self.scenario.pose.provider not in {"manual_sim", "simulated"}:
                        raise ValueError("USB test kit only permits virtual robot pose")
                    source = RadiacodeJsonlSource(detector, self.clock, self.scenario.mission.duration_s)
                elif detector.source_type == "fs5000_serial":
                    source = FS5000SerialSource(
                        detector.serial_port,
                        config=detector,
                        clock=self.clock,
                    )
                else:
                    raise RuntimeError(f"unsupported radiation source: {detector.source_type}")
                self.radiation_sources.append(source)
            self.store = MissionStore(self.mission_directory)
            await self.store.open(self.mission_id, self.scenario, self._started_utc_ns)
            (self.mission_directory / "scenario.yaml").write_text(
                self.scenario.canonical_yaml(), encoding="utf-8"
            )
            (self.mission_directory / "logs.jsonl").touch()
            context = RunContext(
                mission_id=self.mission_id,
                mode=self.scenario.mission.mode,
                time_domain_id=f"mission:{self.mission_id}",
                seed=self.scenario.mission.seed,
                started_utc_ns=self._started_utc_ns,
            )
            await self.pose_source.start(context)
            if self.sport_commander is not None:
                await self.sport_commander.start()
            for source in self.radiation_sources:
                await source.start(context)
            self.state = MissionState.RUNNING
            await self.clock.resume()
            self._runner_task = asyncio.create_task(
                self._run_pipeline(), name=f"mission:{self.mission_id}"
            )
            await self._publish_state()
            self._audit("MISSION_STARTED", {"mission_id": self.mission_id})
            return self.mission_id

    async def pause(self) -> None:
        if any(d.source_type == "radiacode_jsonl" for d in self.scenario.detectors):
            raise ValueError("O teste USB usa tempo real; encerre a missão em vez de pausar")
        if self.state != MissionState.RUNNING or self.clock is None:
            raise RuntimeError("only a running mission can be paused")
        await self.clock.pause()
        self.state = MissionState.PAUSED
        await self._publish_state()
        self._audit("MISSION_PAUSED", {})

    async def resume(self) -> None:
        if self.state != MissionState.PAUSED or self.clock is None:
            raise RuntimeError("only a paused mission can be resumed")
        await self.clock.resume()
        self.state = MissionState.RUNNING
        await self._publish_state()
        self._audit("MISSION_RESUMED", {})

    async def step(self, delta_s: float = 0.1) -> int:
        if self.state != MissionState.PAUSED or self.clock is None:
            raise RuntimeError("step is only available while paused")
        value = await self.clock.step(int(delta_s * 1_000_000_000))
        self._audit("MISSION_STEPPED", {"delta_s": delta_s})
        return value

    async def set_speed(self, speed: float) -> None:
        if any(d.source_type == "radiacode_jsonl" for d in self.scenario.detectors) and speed != 1:
            raise ValueError("O teste USB exige velocidade 1x")
        if self.clock is None:
            self.scenario.mission.simulation_speed = speed
            return
        await self.clock.set_speed(speed)
        self.scenario.mission.simulation_speed = speed
        await self.event_bus.publish("mission_state", self.status())

    async def stop(self, reason: str = "operator_stop") -> None:
        if self.state not in {MissionState.RUNNING, MissionState.PAUSED}:
            return
        self.state = MissionState.STOPPING
        self._stop_reason = reason
        self._stop_requested.set()
        if self.pose_source is not None:
            await self.pose_source.stop()
        for source in self.radiation_sources:
            await source.stop()
        if self.sport_commander is not None:
            await self.sport_commander.stop()
            await self.sport_commander.close()
        if self.clock is not None and self.clock.paused:
            await self.clock.resume()
        await self._publish_state()
        if self._runner_task is not None:
            await self._runner_task

    async def wait_until_complete(self) -> None:
        if self._runner_task is not None:
            await self._runner_task

    async def update_source(self, source_id: str, patch: dict[str, Any]) -> ScenarioEvent:
        field = self.field or RadiationField(
            self.scenario.world,
            self.scenario.radiation_sources,
        )
        self.field = field
        time_ns = self.current_time_ns
        old = field.update_source(
            source_id,
            time_ns / 1_000_000_000,
            x_m=patch.get("x_m"),
            y_m=patch.get("y_m"),
            z_m=patch.get("z_m"),
            strength_uSv_h=patch.get("strength_uSv_h"),
            enabled=patch.get("enabled"),
        )
        event = ScenarioEvent(
            mission_id=self.mission_id or "scenario-configuration",
            simulation_time_ns=time_ns,
            received_utc_ns=time.time_ns(),
            event_type="SOURCE_UPDATED",
            target_id=source_id,
            old_value=old,
            new_value=patch,
        )
        if self.mission_id is not None:
            self._counts["events"] += 1
        if self.store is not None and self.mission_id is not None:
            await self.store.insert_event(event)
        await self.event_bus.publish("scenario_event", event)
        self._audit("SOURCE_UPDATED", event.model_dump(mode="json"))
        return event

    def configure_static_simulation_source(
        self,
        *,
        x_m: float,
        y_m: float,
        dose_rate_at_1m_uSv_h: float,
    ) -> dict[str, float | str | bool]:
        """Replace the simulated truth with one exact static point source.

        This path deliberately replaces keyframes instead of appending events.
        The configured coordinates are therefore the coordinates used from the
        first detector integration window onward.
        """

        if self.state in {
            MissionState.RUNNING,
            MissionState.PAUSED,
            MissionState.STOPPING,
        }:
            raise RuntimeError("stop the active mission before configuring the source")
        if (
            self.scenario.pose.provider not in {"manual_sim", "simulated"}
            or self.scenario.trajectory.type != "manual"
            or not self.scenario.detectors
            or any(detector.source_type != "simulated" for detector in self.scenario.detectors)
        ):
            raise RuntimeError("the minimal interface requires manual simulated pose and radiation")
        bounds = self.scenario.world.bounds_m
        if not bounds.x_min <= x_m <= bounds.x_max:
            raise ValueError(f"x must be between {bounds.x_min:g} and {bounds.x_max:g} m")
        if not bounds.y_min <= y_m <= bounds.y_max:
            raise ValueError(f"y must be between {bounds.y_min:g} and {bounds.y_max:g} m")
        if dose_rate_at_1m_uSv_h <= 0:
            raise ValueError("dose rate at 1 m must be positive")
        if dose_rate_at_1m_uSv_h > MAX_SIMULATION_SOURCE_STRENGTH_USV_H:
            raise ValueError(
                f"dose rate at 1 m cannot exceed {MAX_SIMULATION_SOURCE_STRENGTH_USV_H:g} uSv/h"
            )
        if not self.scenario.radiation_sources:
            raise RuntimeError("the scenario has no simulated source")

        source = self.scenario.radiation_sources[0]
        source_height_m = source.position_keyframes[-1].z_m
        source.model = "inverse_square"
        source.enabled = True
        source.reference_distance_m = 1.0
        source.keyframe_interpolation = "step"
        source.position_keyframes = [
            PositionKeyframeConfig(
                time_s=0.0,
                x_m=float(x_m),
                y_m=float(y_m),
                z_m=source_height_m,
            )
        ]
        source.strength_keyframes = [
            StrengthKeyframeConfig(
                time_s=0.0,
                dose_rate_at_reference_uSv_h=float(dose_rate_at_1m_uSv_h),
            )
        ]
        # The simulation form accepts several orders of magnitude.  Scale only
        # the strength prior to the operator-provided order of magnitude so a
        # 100,000 µSv/h source is not forced into the old 1,000 µSv/h ceiling.
        # Source coordinates remain absent from the inference state.
        strength_range_factor = 100.0
        inferred_minimum = max(
            dose_rate_at_1m_uSv_h / strength_range_factor,
            1e-12,
        )
        inferred_maximum = max(
            dose_rate_at_1m_uSv_h * strength_range_factor,
            inferred_minimum * 10.0,
        )
        inference_payload = self.scenario.inference.model_dump()
        inference_payload.update(
            {
                "source_strength_min_uSv_h": inferred_minimum,
                "source_strength_max_uSv_h": inferred_maximum,
            }
        )
        self.scenario.inference = type(self.scenario.inference).model_validate(inference_payload)
        # Restore the mission-relative logarithmic palette used through V0.4.4.
        # Regulatory public/IOE rates remain available as annotations, but do
        # not force every field above 25 uSv/h into the red colour family.
        scale_minimum, scale_maximum = mission_scale_bounds(
            dose_rate_at_1m_uSv_h,
            background_rate_uSv_h=(self.scenario.world.background.dose_rate_uSv_h),
            physical_minimum_distance_m=(self.scenario.mapping.source_minimum_distance_m),
        )
        self.scenario.dashboard.color_scale = "AresClassic"
        self.scenario.dashboard.scale_mode = "log_fixed"
        self.scenario.dashboard.scale_min_uSv_h = scale_minimum
        self.scenario.dashboard.scale_max_uSv_h = scale_maximum
        self.scenario.dashboard.public_reference_rate_uSv_h = PUBLIC_CONTINUOUS_REFERENCE_RATE_USV_H
        self.scenario.dashboard.ioe_reference_hours_per_year = IOE_REFERENCE_HOURS_PER_YEAR
        self.scenario.dashboard.ioe_recording_rate_uSv_h = IOE_RECORDING_EQUIVALENT_RATE_USV_H
        self.scenario.dashboard.ioe_investigation_rate_uSv_h = (
            IOE_INVESTIGATION_EQUIVALENT_RATE_USV_H
        )
        self.scenario.dashboard.ioe_limit_rate_uSv_h = IOE_LIMIT_EQUIVALENT_RATE_USV_H
        self.scenario.dashboard.ioe_maximum_rate_uSv_h = IOE_MAXIMUM_EQUIVALENT_RATE_USV_H
        self.scenario.dashboard.subtract_background_for_scale = False
        for extra_source in self.scenario.radiation_sources[1:]:
            extra_source.enabled = False
        self.field = RadiationField(
            self.scenario.world,
            self.scenario.radiation_sources,
        )
        return {
            "id": source.id,
            "x_m": float(x_m),
            "y_m": float(y_m),
            "z_m": float(source_height_m),
            "dose_rate_at_1m_uSv_h": float(dose_rate_at_1m_uSv_h),
            "background_uSv_h": float(self.scenario.world.background.dose_rate_uSv_h),
            "enabled": True,
        }

    async def manual_control(
        self,
        linear_m_s: float,
        yaw_rate_rad_s: float,
    ) -> ScenarioEvent:
        if self.mission_id is None:
            raise RuntimeError("start the mission before moving the Go2")
        provider = self.scenario.pose.provider
        old = dict(self._manual_command)
        command = {
            "linear_m_s": float(linear_m_s),
            "yaw_rate_rad_s": float(yaw_rate_rad_s),
        }
        if provider == "unitree_sportmode":
            if self.sport_commander is None:
                raise RuntimeError("real teleop is not available for this mission")
            await self.sport_commander.send(
                command["linear_m_s"], command["yaw_rate_rad_s"]
            )
        elif provider in {"manual_sim", "simulated"} and (
            self.scenario.trajectory.type == "manual"
        ):
            if self.trajectory is None:
                raise RuntimeError("start the mission before moving the simulated Go2")
            self.trajectory.set_manual_command(
                self.current_time_ns / 1_000_000_000,
                command["linear_m_s"],
                command["yaw_rate_rad_s"],
            )
        else:
            raise RuntimeError("the loaded scenario is not configured for manual control")
        self._manual_command = command
        event = ScenarioEvent(
            mission_id=self.mission_id,
            simulation_time_ns=self.current_time_ns,
            received_utc_ns=time.time_ns(),
            event_type="MANUAL_CONTROL",
            target_id="go2",
            old_value=old,
            new_value=command,
        )
        self._counts["events"] += 1
        if self.store is not None:
            await self.store.insert_event(event)
        await self.event_bus.publish("scenario_event", event)
        return event

    async def update_trajectory(self, patch: dict[str, Any]) -> ScenarioEvent:
        if self.trajectory is None or self.mission_id is None:
            raise RuntimeError("no active mission")
        old_speed = self.scenario.trajectory.speed_m_s
        if "speed_m_s" in patch:
            self.trajectory.set_speed(float(patch["speed_m_s"]))
        event = ScenarioEvent(
            mission_id=self.mission_id,
            simulation_time_ns=self.current_time_ns,
            received_utc_ns=time.time_ns(),
            event_type="TRAJECTORY_UPDATED",
            target_id="trajectory",
            old_value={"speed_m_s": old_speed},
            new_value=patch,
        )
        self._counts["events"] += 1
        if self.store is not None:
            await self.store.insert_event(event)
        await self.event_bus.publish("scenario_event", event)
        return event

    async def inject_fault(self, target: str, fault: str) -> ScenarioEvent:
        patch: dict[str, Any]
        if target == "odometry":
            patch = {"dropout_probability": 0.5 if fault == "dropout" else 0.0}
            self.scenario.odometry.dropout_probability = patch["dropout_probability"]
        else:
            detector = next(
                (item for item in self.scenario.detectors if item.sensor_id == target),
                None,
            )
            if detector is None:
                raise KeyError(target)
            if fault == "dropout":
                detector.dropout_probability = 0.5
                patch = {"dropout_probability": 0.5}
            elif fault == "spike":
                detector.outlier_probability = 0.5
                patch = {"outlier_probability": 0.5}
            else:
                raise ValueError(f"unsupported fault: {fault}")
        if self.mission_id is None:
            raise RuntimeError("no active mission")
        event = ScenarioEvent(
            mission_id=self.mission_id,
            simulation_time_ns=self.current_time_ns,
            received_utc_ns=time.time_ns(),
            event_type="FAULT_INJECTED",
            target_id=target,
            new_value={"fault": fault, **patch},
        )
        self._counts["events"] += 1
        if self.store is not None:
            await self.store.insert_event(event)
        await self.event_bus.publish("scenario_event", event)
        return event

    async def map_at(self, time_ns: int) -> MapPrediction:
        if self.map_service is None:
            raise RuntimeError("map is not available")
        return self.map_service.predict(time_ns)

    async def samples(
        self,
        kind: str,
        offset: int = 0,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        if self.mission_directory is None:
            return []
        table = {
            "pose": "pose_samples",
            "radiation": "radiation_samples",
            "mapped": "mapped_samples",
            "observation": "observation_windows",
            "posterior": "source_posteriors",
            "events": "scenario_events",
        }.get(kind)
        if table is None:
            raise ValueError(
                "kind must be pose, radiation, mapped, observation, posterior or events"
            )
        rows = await MissionStore.read_payloads(self.mission_directory / "mission.sqlite", table)
        return rows[offset : offset + min(limit, 5000)]

    async def export(self) -> list[Path]:
        if self.mission_directory is None or self.map_service is None or self.mission_id is None:
            raise RuntimeError("nothing to export")
        prediction = self.latest_map or self.map_service.predict(self.current_time_ns)
        manifest = self._manifest or self._build_manifest(self.state.value, self._stop_reason)
        exporter = MissionExporter(self.mission_directory, self.scenario, prediction, manifest)
        paths = await exporter.export_all()
        self._manifest["exported_files"] = [path.name for path in paths]
        return paths

    @property
    def current_time_ns(self) -> int:
        if self.clock is not None:
            return self.clock.timeline_time_ns()
        return self._replay_time_ns

    def status(self) -> dict[str, Any]:
        telemetry = TelemetrySnapshot(
            mission_id=self.mission_id,
            state=self.state.value,
            simulation_time_ns=self.current_time_ns,
            simulation_speed=(
                self.clock.speed
                if self.clock is not None
                else self.scenario.mission.simulation_speed
            ),
            pose=self.latest_pose,
            radiation=self.latest_radiation,
            mapped_sample=self.latest_mapped,
            sample_count=self._counts["mapped"],
            maximum_observed_uSv_h=(
                max(
                    (sample.dose_rate_uSv_h_filtered for sample in self.map_service.samples),
                    default=None,
                )
                if self.map_service is not None
                else None
            ),
            cumulative_dose_uSv=(
                self.latest_radiation.cumulative_dose_uSv if self.latest_radiation else None
            ),
            map_metrics=self.latest_map.metrics if self.latest_map else {},
            source_posterior=self.latest_posterior,
            exposure=(self.latest_map.exposure if self.latest_map is not None else None),
            alerts=self.alerts[-10:],
        )
        result = telemetry.model_dump(mode="json")
        result["duration_s"] = self.scenario.mission.duration_s
        result["counts"] = dict(self._counts)
        result["queues"] = {
            "observation_pending": self._observation_queue.qsize(),
            "map_snapshot_pending": self._map_snapshot_queue.qsize(),
        }
        result["pipeline_time_ns"] = (
            self.latest_mapped.effective_measurement_time_ns
            if self.latest_mapped is not None
            else 0
        )
        return result

    def health(self) -> dict[str, Any]:
        sources = []
        if self.pose_source is not None:
            sources.append(self.pose_source.health().model_dump(mode="json"))
        sources.extend(source.health().model_dump(mode="json") for source in self.radiation_sources)
        return {
            "schema_version": "1.0",
            "state": self.state.value,
            "sources": sources,
            "synchronizer": {
                "rejected_count": (self.synchronizer.rejected_count if self.synchronizer else 0)
            },
        }

    async def _run_pipeline(self) -> None:
        try:
            assert self.pose_source is not None
            duration_guard = (
                asyncio.create_task(self._stop_sources_at_duration(), name="duration-guard")
                if self.scenario.pose.provider not in {"manual_sim", "simulated"}
                or any(
                    detector.source_type in {"fs5000_serial", "radiacode_jsonl"} for detector in self.scenario.detectors
                )
                else None
            )
            self._inference_task = asyncio.create_task(
                self._inference_loop(), name="posterior-engine"
            )
            pose_task = asyncio.create_task(self._consume_pose(), name="pose-consumer")
            radiation_tasks = [
                asyncio.create_task(
                    self._consume_radiation(source),
                    name=f"radiation-consumer:{source.health().source_id}",
                )
                for source in self.radiation_sources
            ]
            self._map_task = asyncio.create_task(self._map_loop(), name="map-engine")
            self._map_publisher_task = asyncio.create_task(
                self._map_publish_loop(), name="map-publisher"
            )
            await asyncio.gather(pose_task, *radiation_tasks)
            if duration_guard is not None:
                duration_guard.cancel()
                with suppress(asyncio.CancelledError):
                    await duration_guard
            await self._observation_queue.join()
            self._stop_requested.set()
            await self._observation_queue.put(None)
            if self._inference_task is not None:
                await self._inference_task
            if self._map_task is not None:
                await self._map_task
            if self._map_publisher_task is not None:
                await self._map_publisher_task
            await self._finalize(MissionState.COMPLETED)
        except asyncio.CancelledError:
            await self._finalize(MissionState.COMPLETED)
        except Exception as exc:
            self.alerts.append(f"{type(exc).__name__}: {exc}")
            self._audit("MISSION_FAULT", {"error": repr(exc)})
            await self._finalize(MissionState.FAULT)

    async def _stop_sources_at_duration(self) -> None:
        assert self.clock is not None
        await self.clock.wait_until(int((self.scenario.mission.duration_s + 1.0) * 1_000_000_000))
        if self.pose_source is not None:
            await self.pose_source.stop()
        for source in self.radiation_sources:
            await source.stop()
        if self.sport_commander is not None:
            await self.sport_commander.stop()

    async def _consume_pose(self) -> None:
        assert self.pose_source is not None
        assert self.store is not None
        assert self.synchronizer is not None
        try:
            async for sample in self.pose_source.samples():
                if self._stop_requested.is_set():
                    break
                self.latest_pose = sample
                self._counts["pose"] += 1
                self.synchronizer.add_pose(sample)
                async with self._pose_condition:
                    self._pose_condition.notify_all()
                await self.store.insert_pose(sample)
                if (
                    sample.received_monotonic_ns - self._last_pose_publish_monotonic_ns
                    >= 50_000_000
                ):
                    await self.event_bus.publish("pose", sample)
                    self._last_pose_publish_monotonic_ns = sample.received_monotonic_ns
        finally:
            self._pose_finished = True
            async with self._pose_condition:
                self._pose_condition.notify_all()

    async def _consume_radiation(self, source: RadiationSource) -> None:
        assert self.store is not None
        assert self.synchronizer is not None
        assert self.map_service is not None
        async for sample in source.samples():
            if self._stop_requested.is_set():
                break
            self.latest_radiation = sample
            self._counts["radiation"] += 1
            await self.store.insert_radiation(sample)
            await self.event_bus.publish("radiation", sample)
            if sample.is_duplicate:
                self._counts["duplicates"] += 1
                await self.store.insert_alert(
                    sample.mission_id,
                    sample.timeline_time_ns,
                    "INFO",
                    "DUPLICATE_RADIATION",
                    f"Radiation sample {sample.sequence} was stored but not fused",
                )
                continue
            previous = self._previous_radiation.get(sample.sensor_id)
            self._previous_radiation[sample.sensor_id] = sample
            target_time_ns = sample.integration_end_time_ns or sample.effective_measurement_time_ns
            await self._wait_for_pose(target_time_ns)
            detector = next(
                item for item in self.scenario.detectors if item.sensor_id == sample.sensor_id
            )
            if previous is not None:
                recovery = recover_cumulative_gap(
                    previous,
                    sample,
                    detector.cumulative_quantization_uSv,
                )
                if recovery is not None:
                    recovered_sample = sample.model_copy(
                        update={
                            "timeline_time_ns": recovery.end_ns,
                            "source_time_ns": recovery.end_ns,
                            "effective_measurement_time_ns": (recovery.start_ns + recovery.end_ns)
                            // 2,
                            "dose_rate_uSv_h": recovery.rate_uSv_h,
                            "cps": None,
                            "cpm": None,
                            "average_dose_rate_uSv_h": None,
                            "timed_dose_uSv": None,
                            "integration_time_s": recovery.duration_s,
                            "integration_start_time_ns": recovery.start_ns,
                            "integration_end_time_ns": recovery.end_ns,
                            "time_uncertainty_ms": max(
                                sample.time_uncertainty_ms,
                                recovery.rate_uncertainty_uSv_h
                                / max(recovery.rate_uSv_h, 1e-9)
                                * 1000.0,
                            ),
                            "quality": Quality.DEGRADED,
                            "raw_payload": "CUMULATIVE_GAP_RECOVERY",
                            "true_dose_rate_uSv_h": None,
                            "true_sensor_x_m": None,
                            "true_sensor_y_m": None,
                            "true_sensor_z_m": None,
                        }
                    )
                    gap_window = self.synchronizer.build_observation_window(
                        recovered_sample,
                        ObservationMode.DOSE_RATE_ROBUST,
                        EvidenceKind.CUMULATIVE_RECOVERY,
                    )
                    if gap_window is not None:
                        gap_window = gap_window.model_copy(
                            update={
                                "quality_flags": [
                                    *gap_window.quality_flags,
                                    "CUMULATIVE_GAP_RECOVERY",
                                ],
                                "quality": Quality.DEGRADED,
                            }
                        )
                        gap_mapped = self.synchronizer.mapped_from_window(
                            gap_window,
                            recovered_sample,
                        )
                        await self._observation_queue.put((gap_window, gap_mapped))
            window = self.synchronizer.build_observation_window(sample, detector.observation_mode)
            if window is None:
                self._counts["unsynchronized"] += 1
                await self.store.insert_alert(
                    sample.mission_id,
                    sample.timeline_time_ns,
                    "WARNING",
                    "NO_VALID_POSE",
                    f"Radiation sample {sample.sequence} could not be synchronised",
                )
                continue
            mapped = self.synchronizer.mapped_from_window(window, sample)
            await self._observation_queue.put((window, mapped))

    async def _inference_loop(self) -> None:
        assert self.store is not None
        assert self.map_service is not None
        while True:
            item = await self._observation_queue.get()
            try:
                if item is None:
                    return
                window, mapped = item
                update = await asyncio.to_thread(self.map_service.add_observation, window, mapped)
                self.latest_mapped = update.mapped_sample
                self.latest_posterior = update.posterior
                self._counts["mapped"] += 1
                if window.evidence_kind == EvidenceKind.CUMULATIVE_RECOVERY:
                    self._counts["cumulative_recovery"] += 1
                await self.store.insert_observation(window)
                await self.store.insert_mapped(update.mapped_sample)
                await self.store.insert_posterior(update.posterior)
                await self.event_bus.publish("mapped_sample", update.mapped_sample)
                await self.event_bus.publish("source_posterior", update.posterior)
            finally:
                self._observation_queue.task_done()

    async def _wait_for_pose(self, target_time_ns: int) -> None:
        """Give the higher-rate pose producer its configured holdback opportunity.

        This matters especially when a headless simulation runs much faster than
        wall time: the radiation task must not outrun persistence of the pose stream.
        """
        deadline = asyncio.get_running_loop().time() + 2.0
        async with self._pose_condition:
            while not self._pose_finished and (
                self.latest_pose is None or self.latest_pose.timeline_time_ns < target_time_ns
            ):
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(
                        self._pose_condition.wait(),
                        timeout=min(remaining, 0.1),
                    )

    async def _map_loop(self) -> None:
        assert self.clock is not None
        assert self.map_service is not None
        assert self.store is not None
        refresh_period_ns = int(1_000_000_000 / self.scenario.cadence.map_update_hz)
        target_ns = 0
        while not self._stop_requested.is_set():
            try:
                await self.clock.wait_until(target_ns)
            except asyncio.CancelledError:
                break
            processed_time_ns = (
                self.latest_mapped.effective_measurement_time_ns
                if self.latest_mapped is not None
                else 0
            )
            now_ns = min(
                processed_time_ns,
                int(self.scenario.mission.duration_s * 1_000_000_000),
            )
            prediction = await asyncio.to_thread(self.map_service.predict, now_ns)
            self.latest_map = prediction
            second = now_ns // 1_000_000_000
            if second != self._last_snapshot_second and second % 5 == 0:
                await self.store.insert_map(prediction)
                self._last_snapshot_second = second
            if self._map_snapshot_queue.full():
                with suppress(asyncio.QueueEmpty):
                    self._map_snapshot_queue.get_nowait()
                    self._map_snapshot_queue.task_done()
            self._map_snapshot_queue.put_nowait(prediction)
            target_ns = max(
                target_ns + refresh_period_ns,
                self.clock.timeline_time_ns(),
            )
            if target_ns > int((self.scenario.mission.duration_s + 1.0) * 1_000_000_000):
                break

    async def _map_publish_loop(self) -> None:
        while not self._stop_requested.is_set() or not self._map_snapshot_queue.empty():
            try:
                prediction = await asyncio.wait_for(self._map_snapshot_queue.get(), timeout=0.2)
            except asyncio.TimeoutError:
                continue
            try:
                await self.event_bus.publish("map_update", prediction)
                await self.event_bus.publish("metrics", prediction.metrics)
            finally:
                self._map_snapshot_queue.task_done()

    async def _finalize(self, state: MissionState) -> None:
        if self._finalized:
            return
        self._finalized = True
        if self.sport_commander is not None:
            await self.sport_commander.stop()
        if self.clock is not None:
            await self.clock.pause()
        if self.map_service is not None and self.mission_id is not None:
            final_time = min(
                self.current_time_ns,
                int(self.scenario.mission.duration_s * 1_000_000_000),
            )
            self.latest_map = await asyncio.to_thread(self.map_service.predict, final_time)
            self.latest_map.metrics["no_radiation_sample_dropped_by_processing"] = (
                self._counts["unsynchronized"] == 0
            )
            if self.store is not None:
                await self.store.insert_map(self.latest_map)
        self.state = state
        manifest = self._build_manifest(state.value, self._stop_reason)
        self._manifest = manifest
        if self.store is not None and self.mission_id is not None:
            try:
                await self.store.finish(self.mission_id, state.value, time.time_ns(), manifest)
                if self.latest_map is not None and self.mission_directory is not None:
                    exporter = MissionExporter(
                        self.mission_directory,
                        self.scenario,
                        self.latest_map,
                        manifest,
                    )
                    paths = await exporter.export_all()
                    manifest["exported_files"] = [path.name for path in paths]
                    await self.store.finish(self.mission_id, state.value, time.time_ns(), manifest)
            except Exception as exc:
                self.alerts.append(f"EXPORT_OR_STORAGE: {type(exc).__name__}: {exc}")
                self.state = MissionState.FAULT
                manifest["state"] = MissionState.FAULT.value
                manifest["errors"] = list(self.alerts)
                with suppress(Exception):
                    await self.store.finish(
                        self.mission_id,
                        MissionState.FAULT.value,
                        time.time_ns(),
                        manifest,
                    )
            finally:
                await self.store.close()
        if self.mission_directory is not None:
            (self.mission_directory / "scenario.yaml").write_text(
                self.scenario.canonical_yaml(), encoding="utf-8"
            )
            (self.mission_directory / "mission.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        await self._publish_state()
        self._audit("MISSION_FINISHED", {"state": state.value})
        if self.clock is not None:
            await self.clock.stop()

    async def _publish_state(self) -> None:
        await self.event_bus.publish("mission_state", self.status())

    def _build_manifest(self, state: str, reason: str) -> dict[str, Any]:
        return {
            "schema_version": "1.1",
            "mission_id": self.mission_id,
            "name": self.scenario.mission.name,
            "mode": self.scenario.mission.mode,
            "state": state,
            "software_version": __version__,
            "started_utc_ns": self._started_utc_ns,
            "ended_utc_ns": time.time_ns(),
            "seed": self.scenario.mission.seed,
            "configuration_hash": self.scenario.configuration_hash(),
            "time_domain_id": (f"mission:{self.mission_id}" if self.mission_id else None),
            "sources": {
                "pose": self.scenario.pose.model_dump(mode="json"),
                "radiation": [
                    {
                        "sensor_id": detector.sensor_id,
                        "source_type": detector.source_type,
                        "observation_mode": detector.observation_mode,
                        "calibration_id": detector.calibration_id,
                    }
                    for detector in self.scenario.detectors
                ],
            },
            "record_counts": dict(self._counts),
            "rejected_radiation_samples": (
                self.synchronizer.rejected_count if self.synchronizer else 0
            ),
            "mapping": self.scenario.mapping.model_dump(mode="json"),
            "inference": self.scenario.inference.model_dump(mode="json"),
            "adaptive_grid": self.scenario.grid.model_dump(mode="json"),
            "residual": self.scenario.residual.model_dump(mode="json"),
            "cadence": self.scenario.cadence.model_dump(mode="json"),
            "final_metrics": (self.latest_map.metrics if self.latest_map is not None else {}),
            "reason": reason,
            "errors": list(self.alerts),
            "exported_files": [],
        }

    def _make_mission_id(self) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        slug = re.sub(r"[^a-z0-9]+", "-", self.scenario.mission.name.lower()).strip("-")
        return f"{timestamp}-{slug or 'mission'}"

    def _reset_runtime(self) -> None:
        self._stop_requested = asyncio.Event()
        self._pose_condition = asyncio.Condition()
        self._pose_finished = False
        self._finalized = False
        self._stop_reason = "duration_completed"
        self._counts = {
            "pose": 0,
            "radiation": 0,
            "mapped": 0,
            "events": 0,
            "duplicates": 0,
            "unsynchronized": 0,
            "cumulative_recovery": 0,
        }
        self._last_snapshot_second = -1
        self._last_pose_publish_monotonic_ns = 0
        self.alerts = []
        self.latest_pose = None
        self.latest_radiation = None
        self.latest_mapped = None
        self.latest_map = None
        self.latest_posterior = None
        self._observation_queue = asyncio.Queue(maxsize=256)
        self._map_snapshot_queue = asyncio.Queue(maxsize=1)
        self._inference_task = None
        self._map_publisher_task = None
        self._manual_command = {"linear_m_s": 0.0, "yaw_rate_rad_s": 0.0}
        self._previous_radiation = {}

    def _audit(self, event: str, payload: dict[str, Any]) -> None:
        if self.mission_directory is None:
            return
        record = {
            "utc_ns": time.time_ns(),
            "timeline_time_ns": self.current_time_ns,
            "event": event,
            "payload": payload,
        }
        with (self.mission_directory / "logs.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
