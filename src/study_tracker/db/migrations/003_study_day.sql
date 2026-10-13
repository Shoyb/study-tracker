-- Study day cutoff support.
INSERT OR IGNORE INTO settings(key, value) VALUES
    ('day_cutoff_minutes', '180'),
    ('wake_minutes', '420');
PRAGMA user_version = 3;
