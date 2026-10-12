-- Migration 001 – Initial schema for Study Tracker
-- Applied at app startup via migrate.py when user_version = 0.
-- NEVER edit this file after it has been applied to a database.
-- To change the schema, add a new numbered migration file.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ── subjects ────────────────────────────────────────────────────────────────
-- Represents a study subject / category (Physics, Maths, etc.)
CREATE TABLE IF NOT EXISTS subjects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL COLLATE NOCASE,
    colour      TEXT    NOT NULL DEFAULT '#1976D2',  -- hex colour
    sort_order  INTEGER NOT NULL DEFAULT 0,
    archived    INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at  TEXT    NOT NULL,                     -- UTC ISO 8601
    UNIQUE (name)
);

-- ── tasks ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tasks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id      INTEGER NOT NULL REFERENCES subjects(id) ON DELETE RESTRICT,
    title           TEXT    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'todo'
                            CHECK (status IN ('todo', 'in_progress', 'done')),
    priority        TEXT    NOT NULL DEFAULT 'medium'
                            CHECK (priority IN ('low', 'medium', 'high')),
    archived        INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    due_date        TEXT,                             -- YYYY-MM-DD or NULL
    estimate_secs   INTEGER,                          -- NULL means no estimate
    notes           TEXT    NOT NULL DEFAULT '',
    completed_at    TEXT,                             -- UTC ISO 8601 or NULL
    created_at      TEXT    NOT NULL,
    CONSTRAINT done_needs_completed_at
        CHECK (status != 'done' OR completed_at IS NOT NULL)
);

-- ── sessions ────────────────────────────────────────────────────────────────
-- Every recorded study interval.
-- Timed sessions have start_utc and end_utc; duration-only entries have NULL.
CREATE TABLE IF NOT EXISTS sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid            TEXT    NOT NULL UNIQUE,          -- RFC 4122 v4
    subject_id      INTEGER NOT NULL REFERENCES subjects(id) ON DELETE RESTRICT,
    task_id         INTEGER          REFERENCES tasks(id)    ON DELETE RESTRICT,
    local_date      TEXT    NOT NULL,                 -- YYYY-MM-DD (local calendar day)
    start_utc       TEXT,                             -- ISO 8601 Z or NULL
    end_utc         TEXT,                             -- ISO 8601 Z or NULL
    duration_secs   INTEGER NOT NULL CHECK (duration_secs > 0),
    session_type    TEXT    NOT NULL DEFAULT 'timer'
                            CHECK (session_type IN ('timer', 'manual_timed',
                                                    'manual_duration', 'device')),
    notes           TEXT    NOT NULL DEFAULT '',
    utc_offset_mins INTEGER NOT NULL DEFAULT 0,       -- minutes, e.g. 360 for UTC+6
    source          TEXT,                             -- 'csv_import', 'esp32', etc.
    source_id       TEXT,                             -- external identifier for dedup
    created_at      TEXT    NOT NULL,
    CONSTRAINT end_after_start
        CHECK (start_utc IS NULL OR end_utc IS NULL OR end_utc > start_utc),
    CONSTRAINT timed_needs_both_or_neither
        CHECK ((start_utc IS NULL) = (end_utc IS NULL)),
    UNIQUE (source, source_id)                        -- dedup for imports
);

-- ── timer_state ─────────────────────────────────────────────────────────────
-- Persisted state for crash recovery. At most one row (id = 1).
CREATE TABLE IF NOT EXISTS timer_state (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    subject_id      INTEGER NOT NULL REFERENCES subjects(id),
    task_id         INTEGER          REFERENCES tasks(id),
    start_utc       TEXT    NOT NULL,
    last_heartbeat  TEXT    NOT NULL,
    paused_secs     INTEGER NOT NULL DEFAULT 0,
    is_paused       INTEGER NOT NULL DEFAULT 0 CHECK (is_paused IN (0, 1)),
    pause_start     TEXT,                             -- NULL when not paused
    notes           TEXT    NOT NULL DEFAULT ''
);

-- ── settings ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS settings (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL
);

-- ── import_batches ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS import_batches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    filename    TEXT    NOT NULL,
    file_hash   TEXT    NOT NULL,                     -- SHA-256 hex
    imported_at TEXT    NOT NULL,
    row_count   INTEGER NOT NULL
);

-- ── meta ────────────────────────────────────────────────────────────────────
-- Stores schema version and other metadata.
CREATE TABLE IF NOT EXISTS meta (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL
);

INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', '1');

-- ── Seed data ───────────────────────────────────────────────────────────────
INSERT OR IGNORE INTO subjects(name, colour, sort_order, created_at)
VALUES
    ('Physics',     '#1976D2', 1, '2026-10-13T00:00:00Z'),
    ('Mathematics', '#7B1FA2', 2, '2026-10-13T00:00:00Z'),
    ('Chemistry',   '#388E3C', 3, '2026-10-13T00:00:00Z'),
    ('Biology',     '#F57C00', 4, '2026-10-13T00:00:00Z'),
    ('English',     '#C62828', 5, '2026-10-13T00:00:00Z');

INSERT OR IGNORE INTO settings(key, value)
VALUES
    ('week_start',           'saturday'),
    ('theme',                'light'),
    ('streak_threshold_hrs', '6'),
    ('min_session_secs',     '60'),
    ('chart_range_days',     '30'),
    ('auto_backup',          '1'),
    ('backup_copies',        '10');

PRAGMA user_version = 1;
