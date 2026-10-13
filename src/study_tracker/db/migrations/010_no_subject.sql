-- Migration 010 - add a category for sessions without a tracked subject.
INSERT OR IGNORE INTO subjects(name, colour, sort_order, created_at)
VALUES ('No subject', '#757575', 6, '2026-10-13T00:00:00Z');
PRAGMA user_version = 10;