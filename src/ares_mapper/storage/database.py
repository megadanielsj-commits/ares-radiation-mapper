"""One SQLite database per mission."""

from __future__ import annotations

import json
import time
from importlib.resources import files
from pathlib import Path
from typing import Any

import aiosqlite
from pydantic import BaseModel

from ares_mapper.config import ScenarioConfig
from ares_mapper.domain.models import (
    MappedSample,
    MapPrediction,
    ObservationWindow,
    PoseSample,
    RadiationSample,
    ScenarioEvent,
    SourceHealth,
    SourcePosterior,
)


class MissionStore:
    def __init__(self, mission_directory: Path) -> None:
        self.mission_directory = mission_directory
        self.database_path = mission_directory / "mission.sqlite"
        self._connection: aiosqlite.Connection | None = None
        self._pending_writes = 0
        self._flush_interval_s = 2.0
        self._last_commit_monotonic = time.monotonic()

    async def open(
        self,
        mission_id: str,
        scenario: ScenarioConfig,
        started_utc_ns: int,
    ) -> None:
        self.mission_directory.mkdir(parents=True, exist_ok=True)
        self._flush_interval_s = scenario.cadence.persistence_flush_s
        self._last_commit_monotonic = time.monotonic()
        self._connection = await aiosqlite.connect(self.database_path)
        schema = files("ares_mapper.storage").joinpath("schema.sql").read_text(encoding="utf-8")
        await self._connection.executescript(schema)
        await self._connection.execute(
            """
            INSERT OR REPLACE INTO missions(
                mission_id, schema_version, name, mode, state, started_utc_ns,
                configuration_hash, configuration_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mission_id,
                scenario.schema_version,
                scenario.mission.name,
                scenario.mission.mode,
                "RUNNING",
                started_utc_ns,
                scenario.configuration_hash(),
                scenario.model_dump_json(),
            ),
        )
        await self._connection.commit()

    async def insert_pose(self, sample: PoseSample) -> None:
        await self._execute(
            """
            INSERT INTO pose_samples(
                mission_id, sequence, timeline_time_ns, source_id, quality, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                sample.mission_id,
                sample.sequence,
                sample.timeline_time_ns,
                sample.source_id,
                str(sample.quality.value),
                sample.model_dump_json(),
            ),
        )

    async def insert_radiation(self, sample: RadiationSample) -> None:
        await self._execute(
            """
            INSERT INTO radiation_samples(
                mission_id, sequence, timeline_time_ns, sensor_id, quality, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                sample.mission_id,
                sample.sequence,
                sample.timeline_time_ns,
                sample.sensor_id,
                str(sample.quality.value),
                sample.model_dump_json(),
            ),
        )

    async def insert_mapped(self, sample: MappedSample) -> None:
        await self._execute(
            """
            INSERT INTO mapped_samples(
                mission_id, mapped_sequence, timeline_time_ns, sensor_id,
                mapping_quality, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                sample.mission_id,
                sample.mapped_sequence,
                sample.effective_measurement_time_ns,
                sample.sensor_id,
                str(sample.mapping_quality.value),
                sample.model_dump_json(),
            ),
        )

    async def insert_observation(self, window: ObservationWindow) -> None:
        await self._execute(
            """
            INSERT INTO observation_windows(
                mission_id, observation_sequence, integration_end_ns, sensor_id,
                quality, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                window.mission_id,
                window.observation_sequence,
                window.integration_end_ns,
                window.sensor_id,
                str(window.quality.value),
                window.model_dump_json(),
            ),
        )

    async def insert_posterior(self, posterior: SourcePosterior) -> None:
        await self._execute(
            """
            INSERT INTO source_posteriors(
                mission_id, update_sequence, map_time_ns, p_source_exists,
                identifiability_state, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                posterior.mission_id,
                posterior.update_sequence,
                posterior.map_time_ns,
                posterior.p_source_exists,
                str(posterior.identifiability_state.value),
                posterior.model_dump_json(),
            ),
        )

    async def insert_event(self, event: ScenarioEvent) -> None:
        await self._execute(
            """
            INSERT INTO scenario_events(
                mission_id, timeline_time_ns, event_type, target_id, payload_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                event.mission_id,
                event.simulation_time_ns,
                event.event_type,
                event.target_id,
                event.model_dump_json(),
            ),
        )

    async def insert_health(self, mission_id: str, timeline_ns: int, health: SourceHealth) -> None:
        await self._execute(
            """
            INSERT INTO source_health_events(
                mission_id, timeline_time_ns, source_id, state, payload_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                mission_id,
                timeline_ns,
                health.source_id,
                str(health.state.value),
                health.model_dump_json(),
            ),
        )

    async def insert_alert(
        self,
        mission_id: str,
        timeline_ns: int,
        severity: str,
        code: str,
        message: str,
    ) -> None:
        await self._execute(
            """
            INSERT INTO alerts(
                mission_id, timeline_time_ns, severity, code, message
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (mission_id, timeline_ns, severity, code, message),
        )

    async def insert_map(self, prediction: MapPrediction) -> None:
        await self._execute(
            """
            INSERT INTO map_snapshots(
                mission_id, map_time_ns, temporal_mode, payload_json
            ) VALUES (?, ?, ?, ?)
            """,
            (
                prediction.mission_id,
                prediction.map_time_ns,
                prediction.temporal_mode,
                prediction.model_dump_json(),
            ),
        )

    async def finish(
        self,
        mission_id: str,
        state: str,
        ended_utc_ns: int,
        manifest: dict[str, Any],
    ) -> None:
        connection = self._require_connection()
        await connection.execute(
            """
            UPDATE missions
            SET state = ?, ended_utc_ns = ?, manifest_json = ?
            WHERE mission_id = ?
            """,
            (state, ended_utc_ns, json.dumps(manifest, ensure_ascii=False), mission_id),
        )
        await connection.commit()
        self._pending_writes = 0

    async def close(self) -> None:
        if self._connection is None:
            return
        await self._connection.commit()
        await self._connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        await self._connection.close()
        self._connection = None

    async def _execute(self, sql: str, parameters: tuple[Any, ...]) -> None:
        connection = self._require_connection()
        await connection.execute(sql, parameters)
        self._pending_writes += 1
        now = time.monotonic()
        if (
            self._pending_writes >= 50
            or now - self._last_commit_monotonic >= self._flush_interval_s
        ):
            await connection.commit()
            self._pending_writes = 0
            self._last_commit_monotonic = now

    def _require_connection(self) -> aiosqlite.Connection:
        if self._connection is None:
            raise RuntimeError("mission store is not open")
        return self._connection

    @staticmethod
    async def read_payloads(database_path: Path, table: str) -> list[dict[str, Any]]:
        allowed = {
            "pose_samples",
            "radiation_samples",
            "mapped_samples",
            "scenario_events",
            "source_health_events",
            "map_snapshots",
            "observation_windows",
            "source_posteriors",
        }
        if table not in allowed:
            raise ValueError(f"unsupported table: {table}")
        async with aiosqlite.connect(database_path) as connection:
            existence = await connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            )
            if await existence.fetchone() is None:
                return []
            cursor = await connection.execute(f"SELECT payload_json FROM {table} ORDER BY id")
            rows = await cursor.fetchall()
        return [json.loads(row[0]) for row in rows]

    @staticmethod
    async def read_mission(database_path: Path) -> dict[str, Any]:
        async with aiosqlite.connect(database_path) as connection:
            connection.row_factory = aiosqlite.Row
            cursor = await connection.execute("SELECT * FROM missions LIMIT 1")
            row = await cursor.fetchone()
        if row is None:
            raise ValueError("database does not contain a mission")
        return dict(row)


def model_payload(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")
