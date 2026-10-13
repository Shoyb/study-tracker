-- Migration 008 – exam definitions and integer milli-mark scoring.
CREATE TABLE exam_levels (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE CHECK (length(trim(name)) BETWEEN 1 AND 40),
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_archived INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0, 1))
);
CREATE TABLE exam_categories (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE CHECK (length(trim(name)) BETWEEN 1 AND 40),
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_archived INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0, 1))
);
CREATE TABLE scoring_presets (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    marks_per_correct_milli INTEGER NOT NULL DEFAULT 1000 CHECK (marks_per_correct_milli > 0),
    penalty_per_incorrect_milli INTEGER NOT NULL DEFAULT 250 CHECK (penalty_per_incorrect_milli >= 0),
    marks_per_skipped_milli INTEGER NOT NULL DEFAULT 0 CHECK (marks_per_skipped_milli BETWEEN -10000 AND 10000),
    is_archived INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0, 1)),
    sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE exams (
    id INTEGER PRIMARY KEY,
    uuid TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL CHECK (length(trim(title)) BETWEEN 1 AND 200),
    status TEXT NOT NULL DEFAULT 'completed' CHECK (status IN ('planned', 'completed')),
    exam_date TEXT NOT NULL CHECK (exam_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    category_id INTEGER REFERENCES exam_categories(id) ON DELETE RESTRICT,
    level_id INTEGER REFERENCES exam_levels(id) ON DELETE RESTRICT,
    allowed_seconds INTEGER CHECK (allowed_seconds IS NULL OR allowed_seconds > 0),
    taken_seconds INTEGER CHECK (taken_seconds IS NULL OR taken_seconds > 0),
    session_id INTEGER REFERENCES sessions(id) ON DELETE SET NULL,
    notes TEXT NOT NULL DEFAULT '',
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    CHECK (status = 'completed' OR taken_seconds IS NULL)
);
CREATE INDEX ix_exams_date ON exams(exam_date);
CREATE INDEX ix_exams_category_level ON exams(category_id, level_id);
CREATE TABLE exam_parts (
    id INTEGER PRIMARY KEY,
    exam_id INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    position INTEGER NOT NULL DEFAULT 0,
    kind TEXT NOT NULL CHECK (kind IN ('mcq', 'written')),
    subject_id INTEGER REFERENCES subjects(id) ON DELETE RESTRICT,
    label TEXT NOT NULL DEFAULT '',
    total_questions INTEGER CHECK (total_questions IS NULL OR total_questions > 0),
    correct INTEGER CHECK (correct IS NULL OR correct >= 0),
    incorrect INTEGER CHECK (incorrect IS NULL OR incorrect >= 0),
    skipped INTEGER CHECK (skipped IS NULL OR skipped >= 0),
    marks_per_correct_milli INTEGER CHECK (marks_per_correct_milli IS NULL OR marks_per_correct_milli > 0),
    penalty_per_incorrect_milli INTEGER CHECK (penalty_per_incorrect_milli IS NULL OR penalty_per_incorrect_milli >= 0),
    marks_per_skipped_milli INTEGER,
    written_full_milli INTEGER CHECK (written_full_milli IS NULL OR written_full_milli > 0),
    written_obtained_milli INTEGER CHECK (written_obtained_milli IS NULL OR written_obtained_milli >= 0),
    CHECK (kind <> 'mcq' OR (
        total_questions IS NOT NULL AND correct IS NOT NULL AND incorrect IS NOT NULL
        AND skipped IS NOT NULL AND correct + incorrect + skipped = total_questions
        AND marks_per_correct_milli IS NOT NULL AND penalty_per_incorrect_milli IS NOT NULL
        AND marks_per_skipped_milli IS NOT NULL
    )),
    CHECK (kind <> 'written' OR (
        written_full_milli IS NOT NULL AND written_obtained_milli IS NOT NULL
        AND written_obtained_milli <= written_full_milli
    ))
);
CREATE INDEX ix_parts_exam ON exam_parts(exam_id);
CREATE INDEX ix_parts_subject ON exam_parts(subject_id);
INSERT INTO exam_levels (name, sort_order) VALUES ('Engineering', 1), ('Varsity', 2);
INSERT INTO exam_categories (name, sort_order) VALUES
    ('Paper final', 1), ('Weekly', 2), ('Monthly', 3), ('Daily', 4),
    ('Subject final', 5), ('Final model test', 6);
INSERT INTO scoring_presets (name, marks_per_correct_milli, penalty_per_incorrect_milli, sort_order)
VALUES ('MCQ, 0.25 negative', 1000, 250, 1), ('MCQ, no negative', 1000, 0, 2);
PRAGMA user_version = 8;
