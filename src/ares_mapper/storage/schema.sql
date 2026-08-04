PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS missions (
    mission_id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL,
    name TEXT NOT NULL,
    mode TEXT NOT NULL,
    state TEXT NOT NULL,
    started_utc_ns INTEGER NOT NULL,
    ended_utc_ns INTEGER,
    configuration_hash TEXT NOT NULL,
    configuration_json TEXT NOT NULL,
    manifest_json TEXT
);

CREATE TABLE IF NOT EXISTS pose_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    timeline_time_ns INTEGER NOT NULL,
    source_id TEXT NOT NULL,
    quality TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pose_mission_time
ON pose_samples(mission_id, timeline_time_ns);

CREATE TABLE IF NOT EXISTS radiation_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    timeline_time_ns INTEGER NOT NULL,
    sensor_id TEXT NOT NULL,
    quality TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_radiation_mission_time
ON radiation_samples(mission_id, timeline_time_ns);

CREATE TABLE IF NOT EXISTS mapped_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id TEXT NOT NULL,
    mapped_sequence INTEGER NOT NULL,
    timeline_time_ns INTEGER NOT NULL,
    sensor_id TEXT NOT NULL,
    mapping_quality TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mapped_mission_time
ON mapped_samples(mission_id, timeline_time_ns);

CREATE TABLE IF NOT EXISTS observation_windows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id TEXT NOT NULL,
    observation_sequence INTEGER NOT NULL,
    integration_end_ns INTEGER NOT NULL,
    sensor_id TEXT NOT NULL,
    quality TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_observation_mission_time
ON observation_windows(mission_id, integration_end_ns);

CREATE TABLE IF NOT EXISTS source_posteriors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id TEXT NOT NULL,
    update_sequence INTEGER NOT NULL,
    map_time_ns INTEGER NOT NULL,
    p_source_exists REAL NOT NULL,
    identifiability_state TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_posterior_mission_time
ON source_posteriors(mission_id, map_time_ns);

CREATE TABLE IF NOT EXISTS scenario_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id TEXT NOT NULL,
    timeline_time_ns INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scenario_events_mission_time
ON scenario_events(mission_id, timeline_time_ns);

CREATE TABLE IF NOT EXISTS source_health_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id TEXT NOT NULL,
    timeline_time_ns INTEGER NOT NULL,
    source_id TEXT NOT NULL,
    state TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id TEXT NOT NULL,
    timeline_time_ns INTEGER NOT NULL,
    severity TEXT NOT NULL,
    code TEXT NOT NULL,
    message TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS map_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id TEXT NOT NULL,
    map_time_ns INTEGER NOT NULL,
    temporal_mode TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_map_snapshots_mission_time
ON map_snapshots(mission_id, map_time_ns);
