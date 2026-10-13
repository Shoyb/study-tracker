-- Migration 004 – persistent undo journaling.
CREATE TABLE IF NOT EXISTS change_journal (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id       TEXT NOT NULL,
    entity_type    TEXT NOT NULL,
    entity_id      INTEGER NOT NULL,
    action         TEXT NOT NULL,
    summary        TEXT NOT NULL,
    before_json    TEXT,
    after_json     TEXT,
    created_at_utc TEXT NOT NULL,
    undone_at_utc  TEXT
);
CREATE INDEX IF NOT EXISTS ix_change_journal_group ON change_journal(group_id);
PRAGMA user_version = 4;
