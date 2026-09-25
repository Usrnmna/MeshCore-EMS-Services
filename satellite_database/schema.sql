-- Each operation is a documented capability, never a fabricated matrix cell.
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS satellites (
    satellite_id TEXT PRIMARY KEY,
    norad_id INTEGER,
    name TEXT NOT NULL,
    lifecycle TEXT,
    data_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS satellite_norad ON satellites(norad_id);
CREATE TABLE IF NOT EXISTS operations (
    operation_id TEXT PRIMARY KEY,
    satellite_id TEXT NOT NULL REFERENCES satellites(satellite_id),
    name TEXT NOT NULL,
    data_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS operations_by_satellite ON operations(satellite_id);
CREATE TABLE IF NOT EXISTS operation_scopes (
    operation_id TEXT NOT NULL REFERENCES operations(operation_id),
    scope TEXT NOT NULL,
    PRIMARY KEY(operation_id, scope)
);
CREATE TABLE IF NOT EXISTS operation_versions (
    version_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL REFERENCES operations(operation_id),
    recorded_at TEXT NOT NULL,
    data_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS versions_by_operation ON operation_versions(operation_id);
CREATE TABLE IF NOT EXISTS observations (
    observation_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL REFERENCES operations(operation_id),
    status TEXT NOT NULL CHECK(status IN ('active','inactive','scheduled_off','unknown')),
    observed_at TEXT NOT NULL,
    source_url TEXT NOT NULL,
    note TEXT NOT NULL,
    evidence_kind TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS observations_by_operation ON observations(operation_id, observed_at DESC);
CREATE TABLE IF NOT EXISTS reception_reports (
    report_id TEXT PRIMARY KEY,
    operation_id TEXT REFERENCES operations(operation_id),
    satellite_label TEXT NOT NULL,
    mode_label TEXT NOT NULL,
    reported_status TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    source_url TEXT NOT NULL,
    data_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS reports_by_operation ON reception_reports(operation_id);
CREATE TABLE IF NOT EXISTS orbits (
    satellite_id TEXT NOT NULL REFERENCES satellites(satellite_id),
    source_url TEXT NOT NULL,
    format TEXT NOT NULL,
    epoch TEXT,
    fetched_at TEXT NOT NULL,
    data_json TEXT NOT NULL,
    PRIMARY KEY(satellite_id, source_url, format)
);
CREATE TABLE IF NOT EXISTS source_fetches (
    url TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    PRIMARY KEY(url, fetched_at, sha256)
);
CREATE TABLE IF NOT EXISTS refresh_runs (
    run_id INTEGER PRIMARY KEY,
    completed_at TEXT NOT NULL,
    report_json TEXT NOT NULL
);

-- Status freshness is evaluated at query time, so offline data ages honestly.
DROP VIEW IF EXISTS operation_reference;
CREATE VIEW operation_reference AS
SELECT o.operation_id, o.satellite_id, s.norad_id, s.name AS satellite_name,
       s.lifecycle, o.name AS operation_name,
       json_extract(o.data_json, '$.source_reported_status') AS catalog_status,
       json_extract(o.data_json, '$.source_updated_at') AS catalog_updated_at,
       json_extract(o.data_json, '$.present_in_latest_source') AS present_in_latest_source,
       CASE
         WHEN s.lifecycle IN ('decayed','re-entered','future','not launched') THEN 'unknown'
         WHEN e.observation_id IS NULL THEN 'unknown'
         WHEN (SELECT COUNT(DISTINCT status) FROM observations AS conflicting
               WHERE conflicting.operation_id=o.operation_id
               AND julianday(conflicting.observed_at)=julianday(e.observed_at)) > 1 THEN 'unknown'
         WHEN julianday(e.observed_at) > julianday('now') THEN 'unknown'
         WHEN julianday('now') - julianday(e.observed_at) >
           CAST((SELECT value FROM metadata WHERE key='status_max_age_days') AS REAL) THEN 'unknown'
         ELSE e.status
       END AS current_status,
       e.status AS last_evidence_status, e.observed_at AS evidence_at,
       (SELECT COUNT(DISTINCT status) FROM observations AS conflicting
        WHERE conflicting.operation_id=o.operation_id
        AND julianday(conflicting.observed_at)=julianday(e.observed_at)) > 1 AS conflicting_evidence,
       e.source_url AS status_source, e.note AS status_note, e.evidence_kind,
       o.data_json
FROM operations o JOIN satellites s USING(satellite_id)
LEFT JOIN observations e ON e.observation_id = (
  SELECT observation_id FROM observations
  WHERE operation_id=o.operation_id
  ORDER BY julianday(observed_at) DESC, recorded_at DESC, observation_id DESC LIMIT 1
);
