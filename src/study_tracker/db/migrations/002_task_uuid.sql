-- Stable task identities for CSV import and export.
ALTER TABLE tasks ADD COLUMN uuid TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_uuid ON tasks(uuid);
PRAGMA user_version = 2;
