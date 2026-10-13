-- Migration 005 – calendar items and scheduled tasks.
ALTER TABLE tasks ADD COLUMN scheduled_date TEXT
    CHECK (scheduled_date IS NULL OR scheduled_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]');
CREATE TABLE calendar_items (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid           TEXT NOT NULL UNIQUE,
    item_date      TEXT NOT NULL CHECK (item_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    kind           TEXT NOT NULL CHECK (kind IN ('note', 'event')),
    title          TEXT NOT NULL CHECK (length(trim(title)) BETWEEN 1 AND 120),
    body           TEXT NOT NULL DEFAULT '' CHECK (length(body) <= 2000),
    start_time     TEXT CHECK (start_time IS NULL OR start_time GLOB '[0-2][0-9]:[0-5][0-9]'),
    end_time       TEXT CHECK (end_time IS NULL OR end_time GLOB '[0-2][0-9]:[0-5][0-9]'),
    color_hex      TEXT,
    is_done        INTEGER NOT NULL DEFAULT 0 CHECK (is_done IN (0, 1)),
    task_id        INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    CHECK (end_time IS NULL OR start_time IS NOT NULL)
);
CREATE INDEX ix_tasks_scheduled ON tasks(scheduled_date);
CREATE INDEX ix_calendar_date ON calendar_items(item_date);
PRAGMA user_version = 5;
