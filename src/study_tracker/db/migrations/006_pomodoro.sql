-- Migration 006 – Pomodoro presets, runs and persisted timer phases.
CREATE TABLE pomodoro_presets (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    name                     TEXT NOT NULL COLLATE NOCASE UNIQUE,
    focus_seconds            INTEGER NOT NULL CHECK (focus_seconds BETWEEN 60 AND 10800),
    short_break_seconds      INTEGER NOT NULL CHECK (short_break_seconds BETWEEN 0 AND 3600),
    long_break_seconds       INTEGER NOT NULL CHECK (long_break_seconds BETWEEN 0 AND 7200),
    cycles_before_long_break INTEGER NOT NULL CHECK (cycles_before_long_break BETWEEN 1 AND 12),
    auto_start_break         INTEGER NOT NULL DEFAULT 1 CHECK (auto_start_break IN (0, 1)),
    auto_start_focus         INTEGER NOT NULL DEFAULT 0 CHECK (auto_start_focus IN (0, 1)),
    is_archived              INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0, 1)),
    sort_order               INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE pomodoro_runs (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid                     TEXT NOT NULL UNIQUE,
    preset_name              TEXT NOT NULL,
    focus_seconds            INTEGER NOT NULL,
    short_break_seconds      INTEGER NOT NULL,
    long_break_seconds       INTEGER NOT NULL,
    cycles_before_long_break INTEGER NOT NULL,
    started_at_utc           TEXT NOT NULL,
    ended_at_utc             TEXT
);
ALTER TABLE sessions ADD COLUMN pomodoro_run_id INTEGER
    REFERENCES pomodoro_runs(id) ON DELETE SET NULL;
ALTER TABLE sessions ADD COLUMN pomodoro_completed INTEGER
    CHECK (pomodoro_completed IS NULL OR pomodoro_completed IN (0, 1));
ALTER TABLE timer_state ADD COLUMN mode TEXT NOT NULL DEFAULT 'stopwatch'
    CHECK (mode IN ('stopwatch', 'pomodoro'));
ALTER TABLE timer_state ADD COLUMN phase TEXT
    CHECK (phase IS NULL OR phase IN ('focus', 'short_break', 'long_break'));
ALTER TABLE timer_state ADD COLUMN phase_target_seconds INTEGER;
ALTER TABLE timer_state ADD COLUMN completed_focus_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE timer_state ADD COLUMN pomodoro_run_id INTEGER REFERENCES pomodoro_runs(id);
ALTER TABLE timer_state ADD COLUMN preset_focus_seconds INTEGER;
ALTER TABLE timer_state ADD COLUMN preset_short_break_seconds INTEGER;
ALTER TABLE timer_state ADD COLUMN preset_long_break_seconds INTEGER;
ALTER TABLE timer_state ADD COLUMN preset_cycles_before_long_break INTEGER;
ALTER TABLE timer_state ADD COLUMN auto_start_break INTEGER NOT NULL DEFAULT 1;
ALTER TABLE timer_state ADD COLUMN auto_start_focus INTEGER NOT NULL DEFAULT 0;
INSERT INTO pomodoro_presets (
    name, focus_seconds, short_break_seconds, long_break_seconds,
    cycles_before_long_break, sort_order
) VALUES
    ('Classic', 1500, 300, 900, 4, 1),
    ('Deep', 3000, 600, 1200, 3, 2);
PRAGMA user_version = 6;
