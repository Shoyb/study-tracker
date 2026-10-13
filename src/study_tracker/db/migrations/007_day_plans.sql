-- Migration 007 – day plans and per-weekday exam-goal defaults.
CREATE TABLE weekday_defaults (
    weekday              INTEGER PRIMARY KEY CHECK (weekday BETWEEN 0 AND 6),
    study_goal_secs      INTEGER NOT NULL DEFAULT 0 CHECK (study_goal_secs BETWEEN 0 AND 86400),
    exam_goal_type       TEXT NOT NULL DEFAULT 'count'
                         CHECK (exam_goal_type IN ('none', 'count', 'minutes', 'questions')),
    exam_goal_value      INTEGER NOT NULL DEFAULT 1 CHECK (exam_goal_value >= 0)
);
CREATE TABLE day_plans (
    local_date           TEXT PRIMARY KEY CHECK (local_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    study_goal_secs      INTEGER CHECK (study_goal_secs IS NULL OR study_goal_secs BETWEEN 0 AND 86400),
    exam_goal_type       TEXT CHECK (exam_goal_type IS NULL OR exam_goal_type IN ('none', 'count', 'minutes', 'questions')),
    exam_goal_value      INTEGER CHECK (exam_goal_value IS NULL OR exam_goal_value >= 0),
    is_rest_day          INTEGER NOT NULL DEFAULT 0 CHECK (is_rest_day IN (0, 1)),
    notes                TEXT NOT NULL DEFAULT '',
    updated_at_utc       TEXT NOT NULL
);
CREATE TABLE alert_log (
    local_date           TEXT NOT NULL,
    alert_key            TEXT NOT NULL,
    fired_at_utc         TEXT NOT NULL,
    PRIMARY KEY (local_date, alert_key)
);
CREATE TABLE availability_blocks (
    id                   INTEGER PRIMARY KEY,
    label                TEXT NOT NULL,
    weekday_mask         INTEGER NOT NULL CHECK (weekday_mask BETWEEN 1 AND 127),
    start_minutes        INTEGER NOT NULL CHECK (start_minutes BETWEEN 0 AND 1439),
    end_minutes          INTEGER NOT NULL CHECK (end_minutes BETWEEN 1 AND 1440),
    CHECK (end_minutes <> start_minutes)
);
INSERT INTO weekday_defaults (weekday, study_goal_secs, exam_goal_type, exam_goal_value)
VALUES (0, 0, 'count', 1), (1, 0, 'count', 1), (2, 0, 'count', 1),
       (3, 0, 'count', 1), (4, 0, 'count', 1), (5, 0, 'count', 1),
       (6, 0, 'count', 1);
PRAGMA user_version = 7;
