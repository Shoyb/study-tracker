-- Migration 009 - make dark mode the default theme.
UPDATE settings SET value = 'dark' WHERE key = 'theme' AND value = 'light';
PRAGMA user_version = 9;