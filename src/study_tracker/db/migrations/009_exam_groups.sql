-- Migration 009 – manual groups for exam statistics.
CREATE TABLE IF NOT EXISTS exam_groups (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS exam_group_members (
    exam_id   INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    group_id  INTEGER NOT NULL REFERENCES exam_groups(id) ON DELETE CASCADE,
    PRIMARY KEY (exam_id, group_id)
);
PRAGMA user_version = 9;
