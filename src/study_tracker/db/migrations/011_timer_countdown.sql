-- Migration 011 - persist standalone countdown timer state.
ALTER TABLE timer_state ADD COLUMN timer_kind TEXT NOT NULL DEFAULT 'stopwatch'
    CHECK (timer_kind IN ('stopwatch', 'pomodoro', 'countdown'));
ALTER TABLE timer_state ADD COLUMN countdown_target_seconds INTEGER
    CHECK (countdown_target_seconds IS NULL OR countdown_target_seconds BETWEEN 1 AND 86400);
UPDATE timer_state SET timer_kind = 'pomodoro' WHERE mode = 'pomodoro';
PRAGMA user_version = 11;