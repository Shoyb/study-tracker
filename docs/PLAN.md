# Study Tracker — Development Plan

Oct 13, 2026 · @Shoyb

## Summary

**Your proposed stack is sound; I recommend it as written, with three adjustments:** package with PyInstaller in one-folder mode, keep pandas and any ORM out of the app, and drive all timer and date tests with a fake clock. This document is a plan only. Nothing is implemented, and no application code gets written until you approve it.

### Decisions I made where your brief left room

| # | Topic | Decision | Why |
| --- | --- | --- | --- |
| 1 | Timestamps | UTC ISO 8601 text (`2026-10-13T08:15:30Z`), plus the UTC offset at start and a `local_date` column | Sorts correctly as text, survives time-zone changes, and keeps daily grouping simple |
| 2 | Durations | Integer seconds. A timer session stores *active* time, not end minus start | Pauses and sleep gaps never inflate study time |
| 3 | Duration-only entries | `start_utc` and `end_utc` are NULL; only a date and seconds are stored | No invented timestamps |
| 4 | Midnight | One session row. Its seconds are split at local midnight when totals are calculated | Editing stays simple and totals stay exact |
| 5 | Overlaps | One timer at a time. Sessions that have times cannot overlap each other (checked on save, edit and import) | Totals cannot be inflated by accident |
| 6 | Task time | Always calculated as the sum of its sessions, never stored | No totals that can drift out of sync |
| 7 | Task statuses | To do, In progress, Done, plus a separate Archived flag | An archived task still remembers whether it was finished |
| 8 | Deleting tasks and subjects | Blocked while sessions reference them; archive instead | History stays interpretable |
| 9 | Complete a task while its timer runs | Ask; the default is stop, save, then complete | Matches the usual intent, loses nothing |
| 10 | Sleep or app freeze while running | Auto-pause; the gap is not counted unless you choose to count it | Never counts time you were not studying |
| 11 | Crash recovery | Heartbeat saved every 15 s; recovered time stops at the last heartbeat | Under-counts by at most 15 s, never over-counts |
| 12 | Daily average | Includes zero days, starting from your first recorded day | Honest, and not punished by days before you began |
| 13 | Streak | A day counts at 30 minutes or more (adjustable); today does not break a streak until it ends | Clear, fair rule |
| 14 | Week start | Monday by default, changeable in Settings | ISO standard; one setting changes every weekly calculation |
| 15 | Milestone order | Manual entry and history come *before* the timer; automatic backup arrives in milestone 2 | See section J |
| 16 | Packaging | PyInstaller one-folder build, optionally wrapped in an installer | One-file builds start slowly and trigger antivirus warnings more often |

### Questions for you

I used the defaults in brackets, so nothing is blocked. Tell me if you want any changed.

1. Which day should the week start on? \[Saturday\]
2. What is the minimum daily study time that counts toward a streak? \[6 Hour\]
3. Which subjects should be pre-loaded? \[Physics, Mathematics, Chemistry, Biology, English\]
4. For ESP32 sessions with no real clock, may the app ask you to assign a date during import? \[Yes\]

### How to read this plan

Sections A to L match the deliverables in your brief, in the same order. Anything marked *(future)* is intentionally outside the first release.

## A. Architecture recommendation

**Build Study Tracker as a single-process, single-thread Python desktop app: PySide6 (Qt Widgets) for the interface, plain SQLite for storage, Matplotlib for charts.** The code is split into four layers so that calculations and rules can be tested without opening a window.

### Technology verdicts

| Technology | Verdict | Notes |
| --- | --- | --- |
| Python 3.12, 64-bit, from python.org | Required | Do not use the Microsoft Store build: it silently redirects `AppData` writes to a hidden folder, which causes exactly the "empty database in the wrong place" bug you want to avoid. Do not jump to the newest Python minor version until PySide6 and PyInstaller support it. |
| PySide6, Qt Widgets (not QML) | Required | Official Qt binding, LGPL licence. Widgets are plain Python classes, which is far easier for a learner than QML. Styling is done with a stylesheet file. |
| `sqlite3` (standard library) | Required | No ORM. About seven tables of plain SQL is easier to understand and debug than a mapping library. |
| Matplotlib | Required (your choice, confirmed) | You already know it, and exported data will be analysed with it later. Cost: it pulls in NumPy and takes about a second to import, so import it lazily the first time a chart page opens. |
| `csv`, `datetime`, `json`, `logging`, `hashlib` | Required | All standard library. |
| `zoneinfo` | Not needed | Store UTC and use the system's local offset. Windows has no time-zone database, so `zoneinfo` would force an extra `tzdata` package. |
| pytest | Dev only | Test runner. |
| pytest-qt | Optional, dev only | A few "window opens and button works" smoke tests. |
| ruff | Optional, dev only | Linter and formatter. Cheap protection against AI-generated mistakes. |
| PyInstaller | Packaging | Use one-folder (`--onedir`) mode. |
| Inno Setup | Optional | Wraps the folder into a normal installer with a Start-menu shortcut. |
| pandas | Not in the app | Use it only in your own analysis of the exported CSVs. |
| pyserial | Added in milestone 13 only | Needed only for ESP32 transfer. |
| SQLAlchemy, Alembic | Not needed | Migrations are numbered SQL files (section D). |

Expect memory use in the low hundreds of MB, well within 8 GB. This is an estimate: measure it in milestone 11.

### Alternatives that were considered

| Alternative | Verdict |
| --- | --- |
| QtCharts (ships inside PySide6) | The one alternative that could materially help: smaller package, no NumPy, native hover tooltips. Switch only if Matplotlib proves slow or too big. Keep chart code behind small functions so a swap stays possible. |
| pyqtgraph | Fast and interactive, but a different API to learn and still needs NumPy. No clear gain here. |
| Tkinter | Lighter, but dated look and weak tables. Not worth the trade. |
| PyQt6 | Same Qt, GPL or paid licence. PySide6 has no such constraint. |
| Electron or a local web dashboard | You asked for native, and it would be heavier on 8 GB. |
| JSON or CSV files as the database | No transactions, no constraints, easy to corrupt. SQLite is the right tool. |

### Layers

Each layer may only import from layers listed before it. This single rule is what prevents circular imports.

1. **core**: paths, logging, clock, errors. Imports nothing from the project.
2. **domain**: dataclasses and pure functions (midnight splitting, daily totals, streaks, validation). No Qt, no SQL.
3. **db**: connection setup, migrations, and *repositories* (small modules holding the SQL for one table each).
4. **services**: the business rules (timer, tasks, sessions, statistics, export, import, backup). Use `db` and `domain`.
5. **charts**: functions that draw onto a Matplotlib figure from plain data. No Qt.
6. **ui**: windows, pages, dialogs. Talks only to services and domain, never to SQL.

### Key design choices

- **Injectable clock.** Every service receives a `Clock` object with `now_utc()` and `monotonic()`. Tests pass a `FakeClock` they can advance by hand, so "pause for 40 minutes across midnight" runs in milliseconds.
- **One calculation, used everywhere.** Daily totals come from a single function in `domain`. Dashboard, calendar, charts and CSV export all call it, so numbers can never disagree.
- **Everything on the GUI thread.** The data is small (tens of thousands of rows after years of use). Avoiding worker threads removes a whole class of SQLite and Qt bugs.
- **Refresh by signals.** A small `AppSignals` object announces `sessions_changed`, `tasks_changed`, `subjects_changed`, `settings_changed` and `day_changed`. Each page marks itself "dirty" and reloads when next shown, so no page can show stale numbers.
- **SQLite safety settings** on every connection: foreign keys on, WAL journal mode, `synchronous=FULL`, a 5-second busy timeout.

### Concepts in plain words

| Term | Meaning |
| --- | --- |
| Layer | A group of modules with a defined job and a defined set of things it may import |
| Repository | A module that holds all SQL for one table; the rest of the app never writes SQL |
| Service | A module that enforces rules ("no overlapping sessions") and calls repositories inside one transaction |
| Migration | A numbered SQL file that upgrades an old database to the new schema without losing data |
| WAL | SQLite's write-ahead log mode: safer against crashes, but creates `-wal` and `-shm` side files, so file-copy backups are unsafe; use SQLite's backup API |
| Monotonic clock | A clock that only moves forward and ignores the user changing the system time; good for measuring elapsed time |
| Wall clock | The date and time shown on screen; can jump when the user or Windows changes it |
| Signal and slot | Qt's way for one object to announce an event and others to react |
| Fixture and fake clock | Test helpers that create a clean temporary database and a controllable clock |

## B. Feature specification

**Version 1 contains everything in "Must have"; "Should have" is added only after the milestone-11 reliability pass; "Future" is explicitly deferred.**

### Must have (version 1)

- **Subjects:** add, rename, recolour, archive. A built-in "Uncategorized" subject that cannot be removed.
- **Tasks:** create with title only (quick entry); optional description, due date, estimate, priority. Edit, complete, reopen, archive, delete when unused. Search, filter by subject, status, priority and due date; sort by due date, priority, created date, or time spent. Overdue and upcoming highlighting. Estimated versus actual time per task.
- **Timer:** start, pause, resume, stop; subject and optional task; notes; clear elapsed display; today's total; one timer at a time; crash recovery; sleep detection; safe close behaviour.
- **Manual sessions:** add with exact start and end, or with only a date and duration. Link to a task. Validation and overlap checking.
- **History:** sortable, filterable table; edit and delete with confirmation; dashboard and charts refresh automatically.
- **Dashboard:** today, this week, this month, daily average, session count, streak, task statistics, and the required charts A to D.
- **Calendar or daily history:** month grid with each day's total; click a day to see its sessions.
- **Data:** CSV export (sessions, tasks, daily totals, subject summary), manual database backup with validation, restore with safety backup, automatic daily backup.
- **Settings:** data folder location with an "open folder" button, week start, theme, streak threshold, minimum session length.
- **Reliability:** logging to a file, migrations that never lose data, tests for every rule in section G.

### Should have (after the reliability pass)

- Import of previously exported CSV files with preview and duplicate protection.
- Daily study goal drawn as a line on chart A.
- "Still studying?" reminder banner after a long running session (default 4 hours; never changes the recorded time).
- Undo for the last delete during the current run of the app.
- Subject summary and long-format daily-by-subject CSV exports.
- Dark theme.
- Keyboard shortcuts for every main action.
- Windows installer.

### Future (not in version 1)

- ESP32 import over USB serial (milestone 13, designed for now, built later).
- Parent tasks and sub-tasks (a nullable column can be added by a migration).
- Kanban board view.
- Recurring tasks and study goals per subject.
- Tags in addition to subjects.
- Pause and resume events stored as separate segments.
- Portable mode (database beside the executable).
- Optional password or encryption for the database file.

### Deliberately not building

Cloud sync, accounts, a phone app, notifications outside the app, calendar integrations, and a full project-management system. These conflict with your local-first and lightweight constraints.

## C. UI plan

**One main window with a fixed left sidebar of eight items, a stacked content area on the right, and a slim timer bar that stays visible on every page.** There are no nested menus, no tabs inside tabs, and no animation beyond a hover highlight.

### Window layout

- **Sidebar (about 190 px):** Dashboard, Timer, Tasks, History, Calendar, Analytics, Subjects, Settings. The active item is highlighted. Shortcuts Ctrl+1 to Ctrl+8 jump to each page.
- **Content area:** one page at a time (a `QStackedWidget`). Pages load their data when shown, not at startup, so launch stays fast.
- **Timer bar (top of content area):** hidden while idle. While a timer runs or is paused it shows the subject, task, elapsed time and Pause or Resume and Stop buttons, so you can control it from any page.
- **Status line (bottom):** today's total, plus a short message after every save ("Session saved: 1 h 12 min, Physics").
- **Shared behaviour:** every empty list shows a friendly empty state with one button ("No tasks yet. Add your first task"). Every delete asks for confirmation naming what will be removed. Dates display as `Tue 13 Oct 2026`; durations as `2 h 05 min`. Both are stored differently (section D), and display formatting lives in one helper module.

### 1. Dashboard

**Purpose:** answer "how am I doing?" in five seconds.

- Summary tiles: today, this week, this month, daily average, sessions this period, current streak, tasks completed this period.
- A date-range selector (7, 14, 30, 90 days, custom) that controls every chart on this page.
- Charts A (daily bars), B (weekly trend) and C (subjects) in a grid; a compact task panel with overdue count, open count, and the "Next up" list.
- Quick actions: Start timer, Add manual session, Add task.

### 2. Timer

**Purpose:** run a study session with as few clicks as possible.

- Large elapsed-time display, subject drop-down (remembers the last one), optional task drop-down filtered to open tasks of that subject, notes box.
- Buttons: Start, Pause or Resume, Stop and save, Discard (with confirmation).
- Below: today's sessions list and today's running total.
- While running, subject and task are locked; notes stay editable.

### 3. Tasks

**Purpose:** decide what to study next and see progress.

- A table (not a Kanban board; reasoning in section F) with columns: status, title, subject, priority, due date, estimate, time spent, remaining.
- Filter bar: search box, subject, status, priority, due (overdue, this week, none), show archived.
- Right-hand panel or top strip: "Next up" (five tasks), overdue count, total estimated remaining.
- Row actions: start timer on this task, complete or reopen, edit, archive, delete (only if unused).
- "Quick add" line above the table: type a title and press Enter.

### 4. History

**Purpose:** review and correct every recorded session.

- Sortable table: date, start, end, duration, subject, task, type (Timer, Manual with times, Manual duration only, Device), notes.
- Filters: date range, subject, task, type, text in notes. Footer shows the count and total of the filtered rows.
- Buttons: Add session, Edit, Delete. Double-click edits. Multi-select delete is allowed with one confirmation that states the total time being removed.

### 5. Calendar

**Purpose:** see consistency by day at a glance.

- Month grid; each day shows its total and a shade proportional to hours. Previous and next month buttons and a "Today" button.
- Click a day to list its sessions below the grid, with Add and Edit available.

### 6. Analytics

**Purpose:** deeper views than the dashboard.

- Tabs: Time (charts A and B at full size), Subjects (chart C plus a table), Tasks (chart D panels).
- Shared date range, a subject filter, and an "Export this data as CSV" button on every tab.

### 7. Subjects

**Purpose:** manage categories.

- List with colour swatch, name, total time, task count. Add, rename, recolour, reorder, archive and unarchive. Delete is offered only for a subject nothing refers to.

### 8. Settings and data

**Purpose:** preferences and ownership of your data.

- General: week start, theme, streak threshold, minimum session length, default chart range.
- Data: database path with Copy and Open-folder buttons, database size, last backup time.
- Backup: Back up now (choose destination), Restore from backup, automatic backup on or off with the number of copies to keep.
- Export: CSV exports with date range.
- About: version, log file location, Open log folder.

### Navigation flow

The sidebar is the only navigation. Cross-page jumps are always one click and always land on a filtered view: clicking a calendar day edits that day's sessions; clicking a task's time in the Tasks table opens History filtered to that task; clicking a chart bar opens History filtered to that day. Closing the window with a timer running shows a three-way dialog (section E).

### Accessibility basics

Every control reachable by Tab in a logical order; every button has a text label and a keyboard accelerator where sensible; colours are never the only signal (an overdue task shows a text badge as well as red); minimum font 10 pt with a settings option to enlarge.

## D. Database design

**Seven tables: `subjects`, `tasks`, `sessions`, `timer_state`, `settings`, `import_batches` and `meta`. Sessions are the only source of study time; every total is calculated from them.** The schema below is a design specification, not final code.

### Storage rules

- **Timestamps:** UTC, ISO 8601, whole seconds, always ending in `Z` (for example `2026-10-13T08:15:30Z`). Fixed width means text comparison equals time comparison.
- **Dates:** `YYYY-MM-DD` text for calendar days (`local_date`, `due_date`).
- **Durations:** integer seconds. Never floating-point hours.
- **Local date of a session:** stored in `local_date` together with the UTC offset in minutes at the session start, so a later change of Windows time zone cannot move old sessions to other days.
- **Derived, never stored:** task time spent, task remaining time, daily totals, streaks, subject totals.
- **Session types:** `entry_type` says how a row was created (`timer`, `manual`, `device`). Whether exact times are known is simply whether `start_utc` is NULL. The History "type" column combines the two.

### Schema

```sql
-- Run for EVERY connection (it is not stored in the file):
-- PRAGMA foreign_keys = ON; PRAGMA journal_mode = WAL;
-- PRAGMA synchronous = FULL; PRAGMA busy_timeout = 5000;

CREATE TABLE meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL            -- db_instance_id, created_at_utc, created_by_app_version
);

CREATE TABLE subjects (
  id             INTEGER PRIMARY KEY,
  name           TEXT NOT NULL COLLATE NOCASE UNIQUE
                 CHECK (length(trim(name)) BETWEEN 1 AND 60),
  color_hex      TEXT NOT NULL DEFAULT '#4C78A8'
                 CHECK (color_hex GLOB '#[0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f]'),
  sort_order     INTEGER NOT NULL DEFAULT 0,
  is_archived    INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0,1)),
  is_system      INTEGER NOT NULL DEFAULT 0 CHECK (is_system IN (0,1)),   -- 'Uncategorized'
  created_at_utc TEXT NOT NULL
);

CREATE TABLE tasks (
  id               INTEGER PRIMARY KEY,
  uuid             TEXT NOT NULL UNIQUE,            -- stable id for CSV round-trips
  title            TEXT NOT NULL CHECK (length(trim(title)) BETWEEN 1 AND 200),
  description      TEXT NOT NULL DEFAULT '',
  subject_id       INTEGER NOT NULL REFERENCES subjects(id) ON DELETE RESTRICT,
  status           TEXT NOT NULL DEFAULT 'todo' CHECK (status IN ('todo','in_progress','done')),
  priority         INTEGER NOT NULL DEFAULT 2 CHECK (priority IN (1,2,3)),  -- 1 high, 2 normal, 3 low
  due_date         TEXT CHECK (due_date IS NULL OR due_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  estimate_seconds INTEGER CHECK (estimate_seconds IS NULL OR estimate_seconds > 0),
  completed_at_utc TEXT,
  archived_at_utc  TEXT,                            -- NULL = not archived
  created_at_utc   TEXT NOT NULL,
  updated_at_utc   TEXT NOT NULL,
  CHECK ((status = 'done') = (completed_at_utc IS NOT NULL))
);
CREATE INDEX ix_tasks_subject ON tasks(subject_id);
CREATE INDEX ix_tasks_status  ON tasks(status, archived_at_utc);
CREATE INDEX ix_tasks_due     ON tasks(due_date);

CREATE TABLE import_batches (
  id               INTEGER PRIMARY KEY,
  source           TEXT NOT NULL CHECK (source IN ('csv','esp32')),
  filename         TEXT,
  file_sha256      TEXT,
  device_id        TEXT,
  imported_at_utc  TEXT NOT NULL,
  rows_total       INTEGER NOT NULL,
  rows_new         INTEGER NOT NULL,
  rows_duplicate   INTEGER NOT NULL,
  rows_rejected    INTEGER NOT NULL
);

CREATE TABLE sessions (
  id                 INTEGER PRIMARY KEY,
  uuid               TEXT NOT NULL UNIQUE,          -- created at timer start, so a save can never duplicate
  subject_id         INTEGER NOT NULL REFERENCES subjects(id) ON DELETE RESTRICT,
  task_id            INTEGER REFERENCES tasks(id) ON DELETE RESTRICT,
  entry_type         TEXT NOT NULL CHECK (entry_type IN ('timer','manual','device')),
  local_date         TEXT NOT NULL CHECK (local_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  start_utc          TEXT,                          -- NULL when only a duration is known
  end_utc            TEXT,
  utc_offset_minutes INTEGER,                       -- offset in force at start (NULL with start_utc)
  duration_seconds   INTEGER NOT NULL CHECK (duration_seconds > 0 AND duration_seconds <= 86400),
  notes              TEXT NOT NULL DEFAULT '',
  source             TEXT NOT NULL DEFAULT 'app' CHECK (source IN ('app','csv','esp32')),
  source_id          TEXT,                          -- external unique id, used to block duplicate imports
  import_batch_id    INTEGER REFERENCES import_batches(id) ON DELETE SET NULL,
  created_at_utc     TEXT NOT NULL,
  updated_at_utc     TEXT NOT NULL,
  CHECK ((start_utc IS NULL) = (end_utc IS NULL)),
  CHECK ((start_utc IS NULL) = (utc_offset_minutes IS NULL)),
  CHECK (start_utc IS NULL OR end_utc > start_utc),
  CHECK (entry_type <> 'timer' OR start_utc IS NOT NULL)
);
CREATE UNIQUE INDEX ux_sessions_source ON sessions(source, source_id) WHERE source_id IS NOT NULL;
CREATE INDEX ix_sessions_date    ON sessions(local_date);
CREATE INDEX ix_sessions_task    ON sessions(task_id);
CREATE INDEX ix_sessions_subject ON sessions(subject_id);
CREATE INDEX ix_sessions_start   ON sessions(start_utc) WHERE start_utc IS NOT NULL;

CREATE TABLE timer_state (          -- exactly one row, id = 1
  id                  INTEGER PRIMARY KEY CHECK (id = 1),
  state               TEXT NOT NULL DEFAULT 'idle' CHECK (state IN ('idle','running','paused')),
  session_uuid        TEXT,         -- the uuid the saved session will carry
  subject_id          INTEGER REFERENCES subjects(id) ON DELETE RESTRICT,
  task_id             INTEGER REFERENCES tasks(id) ON DELETE RESTRICT,
  notes               TEXT NOT NULL DEFAULT '',
  started_at_utc      TEXT,         -- wall-clock time of the first start
  segment_started_utc TEXT,         -- wall-clock start of the current running stretch (NULL if not running)
  accumulated_seconds INTEGER NOT NULL DEFAULT 0,   -- active seconds banked before this stretch
  last_heartbeat_utc  TEXT,         -- updated every 15 s while running
  updated_at_utc      TEXT NOT NULL
);

CREATE TABLE settings (
  key            TEXT PRIMARY KEY,
  value          TEXT NOT NULL,
  updated_at_utc TEXT NOT NULL
);
```

Settings keys: `week_start`, `theme`, `streak_min_seconds`, `min_session_seconds`, `default_range_days`, `auto_backup_enabled`, `auto_backup_keep`, `daily_goal_seconds`, `long_session_warning_seconds`. Anything the app can recompute does not go in `settings`.

### Why these choices

- **`ON DELETE RESTRICT` everywhere.** SQLite refuses to delete a subject or task that sessions point at, so a bug cannot orphan history. The app also checks first so you see a friendly message instead of a database error.
- **Archive instead of delete.** Archiving a task sets `archived_at_utc` and keeps all sessions. Deleting a task is allowed only when it has no sessions. Deleting a subject is allowed only when no task or session uses it.
- **Session subject is stored on the session**, defaulted from the chosen task. If you later move a task to another subject, past sessions keep the subject they were studied under, which keeps the subject chart truthful.
- **`CHECK` constraints** make the database itself reject impossible rows (negative duration, end before start, a "done" task with no completion time). The application validates first; the constraints are the safety net.
- **Overlap prevention** cannot be a simple constraint because it compares ranges. It is enforced in `session_service` inside a `BEGIN IMMEDIATE` transaction, and tested heavily.
- **Seeded rows:** the first migration inserts Uncategorized (system), Physics, Mathematics, Chemistry and Programming, one `timer_state` row in `idle`, and `meta` entries including a random `db_instance_id`.

### Transactions

Every operation that changes more than one row runs in one transaction: saving a timer session (insert session and reset `timer_state`), completing a task, importing a file (all inserts plus the `import_batches` row), restoring a backup. A failure rolls everything back and leaves the database exactly as it was.

### Migrations

- The schema version lives in SQLite's built-in `PRAGMA user_version`.
- Migrations are files `001_initial.sql`, `002_….sql` and so on, in `db/migrations/`.
- At startup the app compares `user_version` with the highest file number and applies the missing files in order, each inside its own transaction (SQLite DDL is transactional).
- **Before any migration runs, the app makes a safety copy** (`study_tracker_before_v2_20261013.db`) using SQLite's backup API and keeps the last five.
- The app refuses to open a database whose version is *newer* than it understands, with a message to update the app. It never downgrades.
- Never edit an applied migration file; add a new one. Adding a nullable column (`ALTER TABLE … ADD COLUMN`) is the safe, common case.
- Python detail for the implementation: open connections with `isolation_level=None` and issue `BEGIN` and `COMMIT` yourself, because `executescript()` otherwise commits behind your back.

### Data integrity strategy

1. Constraints and foreign keys in the schema, enabled on every connection.
2. `PRAGMA quick_check` at every startup; full `integrity_check` and `foreign_key_check` when validating a backup.
3. Automatic backup at most once per day on startup or exit, keeping the last seven.
4. A safety copy before every migration and before every restore.
5. A `meta.db_instance_id` so the app can tell backups of this database from a different one.
6. Logged startup line with the database path, schema version and row counts.

### Recovery plan

| Situation | What happens |
| --- | --- |
| Database file missing at startup, backups exist | The app does not silently create an empty database. It shows "No database found. Restore the newest backup from \<date>?" with a choice to start fresh. |
| `quick_check` fails | App shows an error, offers to restore the newest valid backup, and tells you where the damaged file is kept (it is renamed, never deleted). |
| You delete sessions by mistake | Undo within the same run (should-have), otherwise restore a backup or re-import your last CSV export. |
| Both database and backups lost | Last resort: your CSV exports. This is why export and import are version-1 features, not extras. |

### Where data lives on Windows, and how the packaged app finds it

**One function, `get_data_dir()` in `core/paths.py`, decides the folder for both the development version and the packaged executable, so they always open the same database.**

| Item | Location |
| --- | --- |
| Data folder | `%LOCALAPPDATA%\StudyTracker\` (Local, not Roaming, so a growing database is not copied by roaming profiles) |
| Database | `study_tracker.db`, plus `-wal` and `-shm` files while the app runs |
| Backups | `backups\` inside the data folder |
| Log | `logs\study_tracker.log`, rotating, 1 MB times 5 files |
| Instance lock | `app.lock` |

- **Resolution order:** (1) the `STUDY_TRACKER_HOME` environment variable if set, used by tests and for development; (2) `%LOCALAPPDATA%\StudyTracker`, created if missing. The result is always an absolute path. Nothing is ever resolved relative to the working directory or the script's folder, which is the usual way a packaged program ends up with a second, empty database.
- **Development habit:** while building, set `STUDY_TRACKER_HOME` to a scratch folder so experiments never touch real data. The packaged executable runs without the variable and therefore uses your real folder.
- **Settings** live in the `settings` table, not in a separate file, so every backup includes them. Every change is saved immediately; there is no Save button anywhere, so there is nothing to forget.
- **Startup order:** take the instance lock, start logging, resolve and log the data folder, check that the database exists (if it is missing and backups exist, offer a restore instead of creating an empty one), run `quick_check`, take the automatic backup if due, apply migrations, load settings, show the window.
- **Logging:** INFO for startup, timer state changes, backups and imports; errors with full tracebacks. Session notes and task text are not written to the log. A user-facing error dialog says what failed in plain words and where the log file is.
- **Graceful exit:** the timer dialog (section E), then flush, make the daily backup if due, close the connection so the WAL file is merged into the database file.
- **Seeing where your data is:** Settings shows the full database path with "Copy path" and "Open folder" buttons, plus the database size and the date of the last backup.

## E. Timer design

**Elapsed time is measured from a clock, never by counting GUI ticks, and the timer's state is saved to the database so that a crash, shutdown or sleep can never silently add or lose study time.** All of this lives in `timer_service`, which has no Qt code; the window only calls it and displays the result.

### Two clocks, two jobs

| Clock | What it is | Used for |
| --- | --- | --- |
| Monotonic (`time.monotonic()`) | Only moves forward; ignores the user or Windows changing the date and time | Measuring how long the timer has been running while the app is open |
| Wall clock (UTC date and time) | What the system clock says; can jump | The `start_utc` and `end_utc` stamps on a saved session, and recovery after a crash |

The GUI timer fires about four times a second only to *redraw* the display. Each redraw asks the service "how much has elapsed?", and the service answers from the clocks. If Windows delays a redraw by two seconds, the display is late, but the recorded time is still correct.

### How elapsed time is calculated

- Starting records `started_at_utc`, a new `session_uuid`, and the current monotonic reading as the *segment start*.
- **Elapsed = banked seconds + (monotonic now minus segment start).**
- **Pause** banks the running stretch into `accumulated_seconds` and clears the segment start. Time while paused is never counted.
- **Resume** starts a new segment.
- **Stop** banks the final stretch, then saves one session in a single transaction: `start_utc` = first start, `end_utc` = now, `duration_seconds` = banked total. The difference between span and duration is the time not counted (pauses, discarded gaps).
- If a wall-clock jump makes the span shorter than the measured duration, the duration wins and `end_utc` is set to `start_utc + duration`. This case gets a test.
- Sessions shorter than the minimum length (default 60 s) ask "Save or discard?" rather than saving noise.

### What is persisted, and when

Every state change (start, pause, resume, change of subject, task or notes) writes the single `timer_state` row immediately. While running, a heartbeat updates `last_heartbeat_utc` every 15 seconds. That is one tiny write, so it is cheap and keeps the worst-case loss small.

### Crash and restart recovery

On startup, if `timer_state` is not `idle`, the app shows a recovery dialog before anything else:

| Saved state | Time the app offers to count | Choices |
| --- | --- | --- |
| Paused | Exactly the banked seconds | Save as a session, resume (stays paused until you press Resume), discard |
| Running | Banked seconds plus (last heartbeat minus segment start), so **never later than the last heartbeat** | Save as a session ending at the last heartbeat, keep it as paused so you can adjust, discard |

The dialog states the numbers plainly ("Physics, started 14:00, last seen alive 14:37, will save 37 min"). Time after the last heartbeat is never counted automatically, so a crash cannot invent study time. The cost is under-counting by at most 15 seconds, which is the correct side to err on.

### Sleep, freezes and clock changes while the app is open

The correct behaviour on sleep differs between Windows versions and Python versions for the monotonic clock, so the design does not depend on it. Instead, every redraw compares how much time passed since the previous one:

- Normal gap: about 0.25 s. Anything over **10 seconds** (wall or monotonic) means the laptop slept, the app froze, or the lid was closed.
- The timer immediately **pauses at the previous redraw's time** and, on the next interaction, shows: "Your computer was inactive from 16:02 to 16:48 (46 min). Resume without counting it (default), resume and count it, or stop and save?"
- If the wall-clock and monotonic gaps disagree by more than 2 seconds, the clock was changed. Elapsed time follows the monotonic clock, and the session note records "system clock changed during session".

### Closing the app or shutting down

Closing the window while a timer is running shows three buttons: **Stop and save**, **Pause and quit** (continue next time; paused time is not counted), **Cancel**. If Windows is shutting down, the app skips the dialog, saves the state as paused and exits. Nothing is lost silently.

### Midnight

A timer that runs past midnight is **not** split while running or saved as two rows. It is one session; the day totals are split by the allocation rule in section G. At the moment the date changes, a `day_changed` signal makes "today" on the Timer page and Dashboard reset correctly.

### Overlaps and multiple timers

Only one timer can exist (`timer_state` has one row). Starting a second shows "A timer is already running for Physics." When stopping, the service checks that the new interval does not overlap any saved session with times; if it does (for example, you added a manual entry for that hour while the timer ran), the dialog shows the conflicting session and lets you trim the new session's start or end, or cancel. Nothing is saved until the conflict is resolved.

### Edge cases the design handles

| Case | Behaviour |
| --- | --- |
| Double-click on Stop | Button disables on first click; the `uuid` unique constraint blocks a second insert even if it got through |
| Running more than 24 h | Save is blocked until you edit the duration to 24 h or less |
| Task completed or archived while its timer runs | Dialog: **Stop, save, then complete (default)**, Complete and keep the timer running, Cancel |
| Subject or task changed while running | Not allowed (controls locked); notes remain editable |
| Database write fails mid-session | Timer keeps counting in memory, a red banner explains, and the app retries on the next heartbeat |
| Two copies of the app opened | Second copy exits with a message (a lock file in the data folder), because two timers writing one database is the one case that corrupts state |

### Testing approach

The `FakeClock` makes every scenario above a normal automated test: advance by 40 minutes, pause, advance across midnight, simulate a crash by building a new service from the same database, simulate sleep by advancing the clock 46 minutes between two redraws, and assert the exact stored seconds.

## F. Task-management design

**Tasks are a first-class table with their own page, and a task's time is always the sum of the sessions linked to it, so tasks and timer can never disagree.** The first version uses a single filterable table, not a Kanban board, and no sub-tasks.

### Fields

| Field | Required | Default and notes |
| --- | --- | --- |
| Title | Yes | 1 to 200 characters. The only field typed in quick-add. |
| Subject | Yes, but pre-filled | Last subject you used, or Uncategorized. It is never blank, so subject filters and charts need no special case. |
| Status | Yes | To do. Values: To do, In progress, Done. |
| Priority | Yes | Normal. Values: High, Normal, Low. |
| Description | No | Free text. |
| Due date | No | A calendar date, no time of day. |
| Estimate | No | Entered as hours and minutes, stored as seconds. |
| Created date | Automatic | Cannot be edited. |
| Completed date | Automatic | Set when status becomes Done, cleared on reopen. |
| Archived | Automatic | A timestamp, not a status. |
| Time spent | Derived | Sum of linked session durations. Never typed. |
| Parent task | Not in version 1 | Subjects already group tasks. A nullable `parent_id` can be added later by a migration without touching history. |

### Statuses and transitions

Your four statuses are all present in the interface. Internally, "Archived" is a flag layered on To do, In progress or Done, so an archived task remembers whether it was finished and can be restored to exactly that state.

- To do to In progress: automatic when the first session is saved against the task (can be switched off), or manual.
- Any to Done: manual "Mark complete" button or checkbox. Sets the completed date.
- Done to In progress or To do: **Reopen**. Clears the completed date. No session is touched.
- Archive and Unarchive: available in any status. Archived tasks disappear from default lists and from the timer's task drop-down, but all their sessions stay in History, charts and exports.

### Relationship to sessions

- A session may link to zero or one task. The link is optional for both timer and manual sessions.
- Time spent on a task is a query: `SUM(duration_seconds)` over sessions with that `task_id`. It is shown in the table, in the timer page's task picker, and in analytics, all from the same function.
- **Completing a task never deletes or edits sessions.**
- **Deleting a task** is allowed only when it has no sessions. If it has any, the app explains "This task has 12 sessions (6 h 40 min). Archive it instead?" and offers Archive. Hard deletion of a task with history is not offered in version 1, which is what guarantees history cannot be corrupted.
- **Changing a task's subject** affects future sessions only. Past sessions keep the subject they were recorded under.
- A session can be re-linked to a different task from History at any time, and the old and new task totals both update at once (they are queries).
- **Completed or archived while a timer runs:** the dialog described in section E; the default is to stop, save, then complete.

### Organising: filter, search, sort

- **Filters** (combinable): subject, status, priority, due (overdue, due in next 7 days, no due date), and a "show archived" switch. Default view: not archived, not done.
- **Search:** case-insensitive match in title and description.
- **Sort:** due date (undated last), priority, created date, time spent, title. Click a column header; the choice is remembered.
- **Overdue** means: due date is before today and status is not Done. An overdue row shows a red "Overdue" badge with the number of days.
- **Estimated versus actual:** shown only for tasks that have an estimate, as "2 h 10 min of 3 h" with a thin progress bar that turns amber past 100%. Tasks without an estimate show time spent only. The app never invents an estimate.

### "What should I study next?"

The **Next up** panel lists the top five open tasks using one fixed, documented ordering, so it is predictable rather than clever:

1. Overdue tasks first (most overdue first).
2. Then tasks with a due date, soonest first.
3. Then higher priority before lower.
4. Then In progress before To do.
5. Then oldest created first.

**Estimated work remaining** = sum over open tasks that have an estimate of `max(estimate minus time spent, 0)`. The panel adds "and N open tasks have no estimate" so the figure is not mistaken for the whole backlog.

### Why a table and not Kanban

A table with filters answers all five of your questions (what is next, what is unfinished, time per task, what is overdue, how much work remains) with one component that is easy to sort, search and test. A Kanban board adds drag-and-drop, column state and layout code for a feature that, for one person, gives little over a status filter. It is listed as a future view over the same data, so nothing needs to be redone.

### Task analytics (feeds chart D)

Time per task, completions per week, estimated versus actual, overdue count and open count. Exact definitions are in section G.

## G. Analytics specification

**Every number in the app comes from one module, `domain/stats.py`, built on one rule for splitting a session across days. Dashboard, calendar, charts and CSV exports all call it, so they cannot disagree.** The rules below are the specification that the unit tests check.

### Statistical definitions

| Quantity | Definition |
| --- | --- |
| Day | A **local calendar day** (midnight to midnight in the computer's time zone at the time of the session). |
| Daily total | Sum, over all sessions, of the seconds that fall on that day under the allocation rules below. Stored as integer seconds; shown as hours and minutes. |
| Session with start and end that stays within one day | All its `duration_seconds` go to that day. |
| **Session crossing midnight** | The span from `start_utc` to `end_utc` is cut at each local midnight. Its `duration_seconds` is shared between the days in proportion to how many seconds of the span fall on each day, using integer arithmetic with the remainder given to the last day, so the parts always add up to the stored duration exactly. Without pauses this is exact. If a pause happened to straddle midnight it is an approximation, and that is stated in the user guide. |
| **Manual entry with only a duration** | All its seconds belong to its `local_date`. It has no time of day, so it is never split and never overlap-checked. |
| Overlap | Sessions with exact times may not overlap (checked on save, edit and import). So summing durations cannot count the same minute twice. Duration-only entries cannot overlap by definition. If a day's total would exceed 24 hours, the save is refused with an explanation. If you enter a duration-only session on a day that already has a lot recorded, a soft warning shows the day's current total. |
| Daily average | Total seconds in the selected range divided by the number of calendar days in the range, **including zero days**. The range starts no earlier than your first recorded day, so days before you began do not drag it down. Today is included and labelled as such. |
| Weekly total | Sum of daily totals from the configured week start through six days later. |
| Session count | Number of session rows with at least one second in the range (a midnight-crossing session counts once in each range it touches, once in the "all time" count). |
| Streak day | A day whose total is at least the streak threshold (default 30 minutes, adjustable). |
| Current streak | Consecutive streak days ending **today if today qualifies, otherwise yesterday**. Today does not break a streak while it is still in progress. |
| Longest streak | The longest run of consecutive streak days in all history. |
| Task completion rate | Tasks completed in the range divided by tasks that were open at any point in the range (created before the end of the range and not completed before its start). Shown as a count and a percentage, and hidden when the denominator is zero. |
| Task time | Sum of `duration_seconds` of sessions linked to the task, regardless of dates (in a date-ranged chart, only sessions allocated to days inside the range). |

### How the calculation is built

1. A repository query fetches sessions whose `local_date` is between the range start minus one day and the range end (the extra day catches sessions that began the evening before).
2. `allocate_by_day(session)` returns `{date: seconds}` for one session. It is a pure function and the most heavily tested one in the project.
3. `daily_totals(sessions, start, end)` adds the allocations and **fills every date in the range with zero**, which is how chart A shows empty days.
4. Everything else (weekly totals, averages, streaks, subject totals) is built on `daily_totals` or on the same allocation.

With tens of thousands of sessions this takes milliseconds in plain Python, so no caching is needed. Add caching only if measuring in milestone 11 shows a need.

### Chart A: daily study time

- **Type:** bar chart. X axis: calendar date. Y axis: hours (a whole-number tick step that suits the range). One bar per day, **including zero days** (a zero day has an empty slot and a tick label).
- **Range:** default last 30 days ending today; buttons for 7, 14, 30, 90 days, and a custom range.
- **Readability:** 14 days or fewer: a label on every bar and a tick label per day. About 30 days: tick labels every second or third day, rotated, with `Mon`-style weekday in a smaller second line. 90 days or more: weekly ticks. Today's bar uses an accent colour. Weekends can be shaded very lightly.
- **Hover:** "Tue 13 Oct 2026: 3 h 25 min, 4 sessions". Click opens History for that day.
- **Optional line:** the daily goal, if you set one.
- **Empty state:** "No study time recorded in this period" with a button to add a session.
- **Refresh:** redraws when `sessions_changed` fires and the page is visible, or the next time it is shown.

### Chart B: weekly trend

- **Purpose:** show consistency, not just volume.
- **Design:** daily totals as a line with markers across the last N weeks (default 8), a 7-day trailing average drawn as a thicker line (zero days included), and a faint vertical line at each week start. A toggle switches to **week overlay**: x axis is the weekday, one line per week for the last four weeks, the current week bold and older weeks faded, which makes "am I more consistent than last month" visible at once.
- **Hover:** the date, the day's total and the week's running total.

### Chart C: subject distribution

- **Type:** horizontal bar chart sorted from most to least time, one bar per subject, each in that subject's colour, labelled with hours and percentage of the period.
- **Why not a pie:** with six to ten subjects, bar lengths are far easier to compare than slice angles.
- **Range and filters:** the shared date range; archived subjects with time in the range are still shown. Subjects with zero time in the range are omitted.
- **Click:** opens History filtered to that subject and range.

### Chart D: task analytics

Three panels on the Analytics Tasks tab, plus a compact version on the Dashboard:

1. **Time per task:** top 10 tasks by time in the range, horizontal bars, coloured by subject.
2. **Estimated versus actual:** for tasks that have an estimate, a pair of bars each (estimate in grey, actual in the accent colour, turning amber when over). Tasks without an estimate are not shown here and a footnote counts them.
3. **Completions:** tasks completed per week as bars, with summary tiles for open, overdue and completion rate.

### General chart rules

- Charts are functions that receive plain data and a Matplotlib `Figure`; they know nothing about Qt or the database, so they can be tested by drawing to an in-memory image.
- One shared style (fonts, colours, spacing) that reads the light or dark theme.
- Every chart has a title, labelled axes with units, and an empty state. No 3-D, no animation, no more than one accent colour besides subject colours.
- Charts redraw only when visible, and never while data is being edited in a dialog.

## H. Export, import and backup design

**Your data leaves the app in three ways: CSV files for analysis, validated SQLite backups for restoring, and (later) a documented line format for ESP32 records. Every import is idempotent, meaning importing the same data twice changes nothing.**

### CSV rules (all exports)

- Encoding **UTF-8 with a byte-order mark** (`utf-8-sig`) so Excel shows Bengali, accented and other non-ASCII text correctly. Files are opened with `newline=''` as Python's `csv` module requires.
- Comma separator, header row always present, one documented column set per file.
- Dates `YYYY-MM-DD`, timestamps `YYYY-MM-DDTHH:MM:SSZ` in UTC, durations in **integer seconds**. Empty cell means "unknown or not applicable" (never 0).
- Exports write to a temporary file and rename it on success, so a failed export never leaves a half-written file or overwrites an earlier good one. If the target name exists, the dialog asks before replacing.
- An optional date range applies to sessions and daily totals.
- A `README` snippet describing each column is saved in `docs/csv-format.md` and shown in the export dialog.

### Export 1: `sessions.csv` (importable)

| Column | Meaning |
| --- | --- |
| `session_uuid` | Unique id of the session; the key used to avoid duplicate imports |
| `local_date` | Calendar date the session is attributed to |
| `start_utc`, `end_utc` | UTC timestamps, empty for duration-only sessions |
| `utc_offset_minutes` | Offset at start, empty if no start |
| `duration_seconds` | Active study seconds |
| `entry_type` | `timer`, `manual` or `device` |
| `subject` | Subject name |
| `task_uuid`, `task_title` | Linked task (uuid is the key, title is for readability) |
| `notes` | Free text |
| `source`, `source_id` | Origin and external id |
| `created_at_utc`, `updated_at_utc` | Audit stamps |

### Export 2: `tasks.csv` (importable)

`task_uuid, title, description, subject, status, priority, due_date, estimate_seconds, created_at_utc, completed_at_utc, archived_at_utc, time_spent_seconds, session_count`. The last two are derived for convenience and are ignored on import.

### Export 3: `daily_totals.csv` (analysis only)

`date, total_seconds, session_count`, one row for **every** day in the range including zero days, using the same calculation as chart A. Use this in Pandas with `pd.read_csv(..., parse_dates=['date'])`.

### Export 4: `subject_summary.csv` and `daily_by_subject.csv` (analysis only)

Subject summary: `subject, total_seconds, session_count, share_of_total`. Daily by subject is in long format, `date, subject, seconds`, ready for a Pandas pivot. Derived hours columns are deliberately omitted from every file except `daily_totals`, where `total_hours` may be added and is labelled derived.

### Backups

- **Always use SQLite's backup API** (`sqlite3.Connection.backup`), never copy the `.db` file by hand: in WAL mode the newest data may still sit in the `-wal` side file, and a plain copy can silently miss it.
- **Manual backup:** you choose the destination; the file is named `study_tracker_YYYY-MM-DD_HHMMSS.db`. The app refuses to overwrite an existing file, so the only existing backup is never replaced by accident.
- **Automatic backup:** once per day at startup or exit into `backups/` in the data folder, keeping the newest seven (configurable). Also made before every migration and before every restore.
- **Validation of any backup** (run right after creating it, and before restoring one): open it read-only; `PRAGMA integrity_check` returns `ok`; `PRAGMA foreign_key_check` returns nothing; `user_version` is known; required tables exist; `meta.db_instance_id` is present; row counts for sessions, tasks and subjects are shown to you. A backup that fails validation is reported and not counted as a backup.
- A backup on the same disk does not protect against disk failure. The Settings page therefore reminds you, if no copy has been made outside the data folder in 30 days, to copy one to a USB drive or cloud-synced folder of your choice. The app itself still uses no cloud.

### Restore

1. You pick a backup file. The app validates it (above) and shows its row counts and date next to the current database's.
2. The app makes a safety backup of the current database first.
3. Timer must be idle (or you are asked to stop it).
4. The connection closes; the new file is copied to a temporary name in the data folder and swapped in with an atomic rename; any stale `-wal` and `-shm` files of the old database are removed (a leftover `-wal` next to a restored file is a classic corruption cause).
5. The app reopens, runs migrations if the backup is from an older version, and refreshes every page. A backup from a *newer* version is refused.

### CSV import (should-have, after the reliability pass)

Import works on `sessions.csv` and `tasks.csv` produced by the app, in this order: tasks first, then sessions.

1. **Parse and validate everything first, write nothing.** Check the header, types, date formats, positive durations, `end > start`, known entry types, and that subjects exist (unknown subjects can be created if you tick a box).
2. **Preview dialog:** "412 rows: 380 new, 25 already in the database, 7 rejected." Rejected rows are listed with the line number and a plain reason, and can be saved as `import_errors.csv`.
3. **Duplicate rules:** a row whose `session_uuid` already exists is skipped, never overwritten. A row with the same `(source, source_id)` is skipped. A file whose SHA-256 hash matches an earlier `import_batches` row triggers "This exact file was already imported on \<date>".
4. **Overlap rule:** an imported session with times that overlaps an existing one is rejected and reported, exactly like a manual entry.
5. **Commit:** all accepted rows plus one `import_batches` row go in a single transaction. If anything fails, nothing is written.

### Database restore versus CSV import

Restore replaces the whole database with a snapshot. Import adds missing rows to the current database. They are different tools: use restore for disaster recovery and import for merging data or moving between machines.

### ESP32 import interface and shared data format *(future; designed now so nothing needs rewriting)*

**The device stores one line of text per finished session in its own flash, and the desktop app imports those lines through the same preview-and-deduplicate pipeline as CSV.** No RTC is assumed. The firmware is not part of this project; only the contract is.

**Record format:** one JSON object per line ("JSON Lines"), plain ASCII, sent over USB serial.

```json
{"v":1,"dev":"a3f91c07","epoch":"5d21b8e4","seq":42,"boot":7,"t0_ms":1823400,"dur_s":2712,"subj":2,"rtc":false,"crc":"9b1c4e02"}
```

| Field | Meaning |
| --- | --- |
| `v` | Format version, so the app can reject or adapt to future formats |
| `dev` | Device id (for example derived from the chip's unique id) |
| `epoch` | Random value created when the device's flash storage is first initialised or erased; stops sequence numbers colliding after a re-flash |
| `seq` | Counter increasing by 1 per saved session, kept in flash |
| `boot` | Power-up counter |
| `t0_ms` | Milliseconds since power-up when the session started (device-local, not a date) |
| `dur_s` | Active seconds, pauses excluded |
| `subj` | Small integer category id; the app maps ids to subject names in Settings, so the device never stores names |
| `rtc` | `true` only if the device has a trustworthy clock |
| `start` | Present only when `rtc` is true: UTC timestamp, same format as the CSV files |
| `crc` | CRC-32 of the other fields, to detect corrupted lines |

**Mapping to the database:** `source = 'esp32'`, `source_id = dev:epoch:seq`, `entry_type = 'device'`. The existing unique index on `(source, source_id)` is what makes duplicate imports impossible. A row without `start` becomes a duration-only session.

**Transfer protocol (text commands, PC to device):**

1. `HELLO` returns device id, epoch, record count and whether it has an RTC.
2. `DUMP <after_seq>` streams every record after that sequence number, then an end line with the record count and last sequence number.
3. The app validates every line, previews, and commits in one transaction.
4. Only after the commit does the app send `ACK <last_seq>`. The device marks those records as transferred but deletes them only when flash is nearly full, oldest first. A lost ACK therefore costs nothing: the next dump repeats the records and the duplicate check skips them.

**Edge cases:**

| Case | Behaviour |
| --- | --- |
| No RTC, so no date | The import dialog lists each record with its duration and a date picker (default today). You confirm the dates. Sessions are stored as duration-only with the date you chose. Timestamps are never invented. |
| Corrupt or malformed line | CRC mismatch, bad JSON, missing field or non-positive duration: the line is rejected and listed with its line number. Other lines proceed. |
| Partial transfer (no end line) | The app reports how many valid records arrived and offers to import them. Doing so is safe because a later full transfer skips them. |
| Device reset or power loss | `seq` and `epoch` live in flash, so numbering continues. A torn write fails its CRC and is skipped. |
| Flash erased or re-flashed | A new `epoch` makes the new records distinct even if `seq` restarts at 1. If `seq` goes *backwards* within the same epoch, the app warns about an anomaly instead of guessing. |
| Two devices | `dev` is part of the key; each device has its own subject mapping. |

**Desktop code to prepare now (without implementing it):** the importer takes an iterable of text lines, so it is tested from a text file and needs no hardware. Only a thin `serial_transport` module, added in milestone 13, imports `pyserial`.

## I. Project folder structure

**Use a `src/` layout with one package, `study_tracker`, organised by the six layers from section A; files stay small (a few hundred lines at most) and each has one job.** Files marked *(later)* are not created until their milestone.

```text
study-tracker/
├─ pyproject.toml               # project metadata, pytest and ruff settings
├─ requirements.txt             # PySide6, matplotlib (version ranges)
├─ requirements-dev.txt         # -r requirements.txt, pytest, pytest-qt, ruff, pyinstaller
├─ README.md
├─ AGENTS.md                    # rules for your AI coding assistant (see section L)
├─ .gitignore                   # .venv, __pycache__, *.db, dist, build, logs
├─ docs/
│  ├─ PLAN.md                   # this plan, saved into the repo
│  ├─ csv-format.md
│  └─ device-protocol.md        # (later)
├─ src/study_tracker/
│  ├─ __init__.py               # __version__
│  ├─ __main__.py               # lets you run: python -m study_tracker
│  ├─ app.py                    # builds QApplication, opens DB, wires services to UI
│  ├─ core/                     # LAYER 1 - imports nothing from the project
│  │  ├─ paths.py               # the ONE place that decides where data lives
│  │  ├─ clock.py               # Clock, SystemClock, (FakeClock lives in tests)
│  │  ├─ logging_setup.py
│  │  ├─ errors.py              # ValidationError, OverlapError, ...
│  │  └─ formatting.py          # '2 h 05 min', '13 Oct 2026'
│  ├─ domain/                   # LAYER 2 - pure Python, no Qt, no SQL
│  │  ├─ models.py              # dataclasses: Subject, Task, Session, TimerState
│  │  ├─ allocation.py          # allocate_by_day()
│  │  ├─ stats.py               # daily_totals, averages, streaks, task stats
│  │  └─ validation.py          # rules for sessions, tasks, subjects
│  ├─ db/                       # LAYER 3 - SQL lives only here
│  │  ├─ connection.py          # open_db(), pragmas
│  │  ├─ migrate.py             # applies migrations, pre-migration backup
│  │  ├─ migrations/001_initial.sql
│  │  ├─ subjects_repo.py   tasks_repo.py   sessions_repo.py
│  │  └─ timer_repo.py   settings_repo.py   imports_repo.py
│  ├─ services/                 # LAYER 4 - business rules, one transaction per action
│  │  ├─ subject_service.py   task_service.py   session_service.py
│  │  ├─ timer_service.py     stats_service.py  settings_service.py
│  │  ├─ export_service.py    backup_service.py import_service.py
│  │  └─ device_import/        # (later) parser.py, serial_transport.py
│  ├─ charts/                   # LAYER 5 - Matplotlib only, no Qt, no DB
│  │  ├─ style.py   daily_bar.py   weekly_trend.py
│  │  └─ subject_chart.py   task_charts.py
│  └─ ui/                       # LAYER 6 - Qt widgets; talks to services only
│     ├─ main_window.py   sidebar.py   timer_bar.py   signals.py
│     ├─ theme/ light.qss   dark.qss
│     ├─ widgets/ duration_edit.py  mpl_canvas.py  empty_state.py  confirm.py
│     ├─ dialogs/ session_dialog.py  task_dialog.py  recovery_dialog.py  import_preview.py
│     └─ pages/ dashboard.py  timer_page.py  tasks_page.py  history_page.py
│               calendar_page.py  analytics_page.py  subjects_page.py  settings_page.py
├─ tests/
│  ├─ conftest.py               # temp database fixture, FakeClock fixture
│  ├─ unit/                     # allocation, stats, validation (no database)
│  ├─ integration/              # services + real SQLite in a temp folder
│  └─ ui/                       # a few pytest-qt smoke tests
└─ packaging/
   ├─ study_tracker.spec        # PyInstaller recipe (later)
   ├─ icon.ico
   └─ build.ps1
```

### Who may import whom

| Module group | May import | Must never import |
| --- | --- | --- |
| `core` | standard library only | everything else in the project |
| `domain` | `core` | `db`, `services`, `charts`, `ui`, any Qt, `sqlite3` |
| `db` | `core`, `domain` | `services`, `charts`, `ui`, any Qt |
| `services` | `core`, `domain`, `db` | `ui`, `charts`, any Qt (signals are emitted by the UI layer after a service call returns) |
| `charts` | `core`, `domain` (plain data types only), `matplotlib` | `db`, `services`, `ui`, Qt |
| `ui` | everything above | direct SQL, `sqlite3` |
| `app.py` | everything | nothing may import `app.py` |

### Rules that keep it from getting tangled

1. **Arrows only point down the table.** A module that wants something from above is a design smell; move the shared piece down a layer.
2. **One owner for each fact.** Paths are decided only in `core/paths.py`, SQL appears only in `db/`, date-splitting only in `domain/allocation.py`, colours only in `charts/style.py` and the theme files.
3. **Services receive their dependencies** (connection, clock) as arguments instead of creating them. That is dependency injection in its simplest form, and it is what lets tests swap in a temporary database and a fake clock.
4. **No global mutable state** except the one `AppSignals` object created in `app.py` and passed to pages.
5. **Do not create a base class, plugin system or abstract factory.** Plain functions and a handful of small classes are enough for this project, and far easier for you and an AI assistant to keep correct.
6. **A circular import means a rule was broken.** Fix the dependency direction rather than importing inside a function.

## J. Milestone roadmap

**Thirteen milestones; each ends with a runnable app, a green test run and a git tag, so you can always go back to the last working version.** Your suggested order is kept, with two deliberate changes:

1. **Manual sessions (milestone 5) and History (6) come before the timer (7).** Both create sessions through the same `session_service`, and manual entry is far simpler than a crash-safe timer. It forces the hard rules (validation, overlap checking, midnight splitting) to be written and tested first, and you get real data into the app a week earlier. The timer then reuses tested code instead of inventing its own.
2. **Backup creation and validation arrive in milestone 2**, not 10. Your data is protected from the first day it exists. Milestone 10 adds the screens, restore flow and CSV.

The Calendar page is built together with the Dashboard in milestone 8, because both need the daily totals.

| # | Milestone | Needs | Tag |
| --- | --- | --- | --- |
| 1 | Project setup and application skeleton | none | `m1` |
| 2 | Database schema, migrations, repositories, backup core | 1 | `m2` |
| 3 | Subject management | 2 | `m3` |
| 4 | Task management | 3 | `m4` |
| 5 | Manual session entry and the core rules | 4 | `m5` |
| 6 | Session history and editing | 5 | `m6` |
| 7 | Stopwatch with persistent state and crash recovery | 6 | `m7` |
| 8 | Daily totals, Calendar and Dashboard | 7 | `m8` |
| 9 | Charts and Analytics | 8 | `m9` |
| 10 | CSV export, backup and restore screens, CSV import | 9 | `m10` |
| 11 | Reliability testing and edge cases | 10 | `m11` |
| 12 | UI polish and Windows packaging | 11 | `v1.0.0` |
| 13 | ESP32 import | 12 | `m13` |

### Definition of done (applies to every milestone)

1. The app starts from an empty data folder and from an existing one.
2. `pytest -q` passes and `ruff check .` is clean.
3. Every new rule has a test, written before or together with the code.
4. The milestone's manual checklist has been run by you.
5. Changes committed and tagged. **Back up your real database before trying a new milestone on real data.**

### Milestone 1: Project setup and application skeleton

- **Objective:** a window that opens and closes cleanly, writes a log, knows where its data lives, and refuses to run twice.
- **Features:** virtual environment; package skeleton; `paths.py` choosing `%LOCALAPPDATA%\StudyTracker` (overridable with the `STUDY_TRACKER_HOME` environment variable for tests); rotating log file; `Clock`; main window with the eight-item sidebar and empty placeholder pages; stylesheet loading; single-instance lock; `AppSignals`.
- **Files:** `pyproject.toml`, `requirements*.txt`, `.gitignore`, `AGENTS.md`, `src/study_tracker/{__init__,__main__,app}.py`, `core/{paths,clock,logging_setup,errors,formatting}.py`, `ui/{main_window,sidebar,signals}.py`, `ui/theme/light.qss`, `tests/conftest.py`, `tests/unit/test_paths.py`, `tests/unit/test_formatting.py`.
- **Dependencies:** PySide6; pytest and ruff for development.
- **Sequence:** (1) repository, virtual environment, installs (section L). (2) `core` modules with their tests. (3) bare `QApplication` and empty window. (4) sidebar and eight placeholder pages. (5) logging and the single-instance lock. (6) commit.
- **Run:** `python -m study_tracker`, `pytest -q`, `ruff check .`
- **Acceptance:** eight sidebar items switch pages by mouse and Ctrl+1 to Ctrl+8; a log file appears in the data folder; a second launch shows a message and exits; with `STUDY_TRACKER_HOME` pointing to a temporary folder nothing is written anywhere else; running from a different working directory behaves identically.
- **Failure modes:** PowerShell refuses to run the venv activation script; Microsoft Store Python; Qt "platform plugin" errors from a broken install (reinstall PySide6); stylesheet path relative to the working directory instead of the package.
- **Checkpoint:** tag `m1`.

### Milestone 2: Database schema, migrations, repositories, backup core

- **Objective:** create, open, migrate and back up the database safely, with tests and no UI.
- **Features:** `001_initial.sql` exactly as in section D; connection pragmas; migration runner using `user_version` with a safety copy; seed rows; one repository per table with the basic operations; startup `quick_check`; "database missing but backups exist" detection; `backup_service.create_backup` and `validate_backup`; a startup log line with the path, version and row counts.
- **Files:** `db/*`, `db/migrations/001_initial.sql`, `services/backup_service.py` (create and validate only), additions to `core/paths.py`, `tests/integration/{test_migrations,test_constraints,test_backup_validate}.py`.
- **Dependencies:** none new.
- **Sequence:** (1) write the SQL file. (2) `connection.py` with pragmas. (3) `migrate.py` and seeding. (4) repositories, each with one test. (5) backup create and validate. (6) call these from `app.py` at startup (logging only).
- **Run:** `pytest -q`; start the app, then open the `.db` file with a viewer such as the VS Code "SQLite Viewer" extension or DB Browser for SQLite and check the tables.
- **Acceptance (all automated):** a fresh start creates a version-1 database with the seed rows; a second start changes nothing; the database rejects a negative duration, `end <= start`, a done task without a completion time, deleting a subject that tasks use, and a duplicate `(source, source_id)`; a test migration that adds a column keeps every row and leaves a safety copy; a backup made while data sits in the WAL file contains every row and validates; a corrupted copy fails validation; foreign keys are proven *enforced* on a fresh connection.
- **Failure modes:** forgetting the foreign-key pragma on a connection; `executescript` committing early; copying the `.db` file instead of using the backup API; using a connection from a second thread; user names with spaces or non-ASCII characters in paths.
- **Checkpoint:** tag `m2`.

### Milestone 3: Subject management

- **Objective:** the Subjects page working end to end through a service.
- **Features:** `subject_service` (create, rename, recolour, reorder, archive, unarchive, delete only when unused); validation (case-insensitive unique name, length); page with list, add and edit dialog with colour picker; confirmation dialog helper; empty state; `subjects_changed` signal.
- **Files:** `services/subject_service.py`, `domain/validation.py` (subject rules), `ui/pages/subjects_page.py`, `ui/widgets/confirm.py`, tests.
- **Dependencies:** none new.
- **Sequence:** (1) validation and service with tests. (2) list view. (3) add and edit dialog. (4) archive and delete flows. (5) signal wiring.
- **Run:** `python -m study_tracker`, then Subjects page.
- **Acceptance:** adding "Physics 2" works; adding "physics 2" shows a friendly duplicate message; Uncategorized cannot be renamed, archived or deleted; deleting a referenced subject is blocked with an explanation (tested by inserting a task directly); archived subjects disappear from pickers but remain visible in history later; other pages learn of changes through the signal.
- **Failure modes:** cancelling the colour dialog returning an invalid colour; trailing spaces in names; a raw database error reaching the user instead of a translated message; list not refreshing.
- **Checkpoint:** tag `m3`.

### Milestone 4: Task management

- **Objective:** the complete task system of section F, without sessions yet.
- **Features:** `task_service` (quick add, edit, status transitions, complete, reopen, archive, unarchive, delete only if unused); table model with sorting and filtering; filter bar and search; overdue badges; "Next up" panel; estimated-versus-actual display (time spent reads 0 until milestone 5); quick-add line; task dialog.
- **Files:** `services/task_service.py`, `domain/stats.py` (`is_overdue`, `next_up`), `db/tasks_repo.py` (filtered list query that also returns time spent), `ui/pages/tasks_page.py`, `ui/dialogs/task_dialog.py`, tests.
- **Dependencies:** none new.
- **Sequence:** (1) domain rules and tests. (2) service. (3) table with sort. (4) filters and search. (5) dialog. (6) Next up panel. (7) archive and delete flows.
- **Run:** `python -m study_tracker`, then Tasks page; `pytest -q`.
- **Acceptance:** quick add creates a To do task with the last-used subject; Done sets the completed date and Reopen clears it; overdue is judged against the fake clock in tests; Next up order matches the five rules in section F; archived tasks hide by default; deleting a task that has a session is refused (the test inserts a session through the repository); combined filters work; 500 generated tasks scroll smoothly.
- **Failure modes:** filter logic written twice (in SQL and in the UI), so choose one place; mixing dates and datetimes for due dates; "today" read from the system instead of the `Clock`; the table not refreshing after an edit; text sorting of numeric columns (give the model a raw-value sort role).
- **Checkpoint:** tag `m4`.

### Milestone 5: Manual session entry and the core rules

- **Objective:** record study time by hand with the correct validation, overlap and midnight rules.
- **Features:** `allocate_by_day()`; session validation; `session_service.add_manual` for sessions with times and duration-only sessions; overlap check inside `BEGIN IMMEDIATE`; `local_date` and offset capture; the session dialog (date, start and end *or* duration, subject, task, notes, a live "calculated duration" label); task time spent now real; first session moves a To do task to In progress; status-line message after saving.
- **Files:** `domain/allocation.py`, `domain/validation.py`, `services/session_service.py`, `db/sessions_repo.py`, `ui/dialogs/session_dialog.py`, `ui/widgets/duration_edit.py`, `tests/unit/{test_allocation,test_validation}.py`, `tests/integration/test_session_service.py`.
- **Dependencies:** none new.
- **Sequence:** (1) allocation function with tests first. (2) validation. (3) repository and service. (4) overlap check and its tests. (5) dialog. (6) wiring and signals.
- **Run:** `pytest -q`; add sessions for several past days in the app.
- **Acceptance:** 23:30 to 00:30 allocates 1800 s to each day; a span over three days allocates correctly; allocations always sum to the stored duration (randomised test); sessions that touch (end equals next start) are allowed and a one-second overlap is rejected; editing a session ignores itself in the overlap check; a duration-only session stores NULL times and the chosen date; end before start, zero duration, more than 24 hours, and a start in the future are rejected with clear messages; the task's time spent updates.
- **Failure modes:** mixing naive and timezone-aware datetimes; entering local time and storing it as if it were UTC; off-by-one on the exclusive end of an interval; Qt date widgets defaulting to a stale "now"; forgetting the overlap check on edit.
- **Checkpoint:** tag `m5`. You should be able to explain each rule of section G in your own words.

### Milestone 6: Session history and editing

- **Objective:** browse, filter, correct and delete sessions safely.
- **Features:** History page with sortable table; filters for date range, subject, task, type and notes text; footer with count and total of the filtered rows; edit through the same dialog (start or end changes keep the "not counted" time; duration may be lowered but not raised above the span); re-link to another task; delete with a confirmation that names the total time removed, multi-select allowed; signals so Tasks and any open page refresh.
- **Files:** `ui/pages/history_page.py`, additions to `services/session_service.py` (update, delete, filtered list) and `db/sessions_repo.py`, tests.
- **Dependencies:** none new.
- **Sequence:** (1) filtered query with tests. (2) table. (3) filter bar. (4) edit flow. (5) delete flow. (6) signals.
- **Run:** `python -m study_tracker`; `pytest -q`.
- **Acceptance:** editing times updates the duration as specified; moving a session to another day updates `local_date`; an edit that would overlap another session is rejected and names the conflict; deleting updates the task's time spent; the footer total equals the sum of visible rows; 5,000 generated sessions load in about a second or less.
- **Failure modes:** filter state lost on refresh; editing a session that was deleted in the meantime; `local_date` not recomputed after a time edit; selection pointing at a row that no longer exists after reload.
- **Checkpoint:** tag `m6`. Enter a real week of study.

### Milestone 7: Stopwatch with persistent state and crash recovery

- **Objective:** the timer exactly as designed in section E.
- **Features:** `timer_service` (start, pause, resume, stop, discard, redraw tick with gap detection, 15-second heartbeat, recovery); Timer page and top timer bar; recovery dialog; close-window dialog; "complete task while timer runs" dialog; today's total including the live portion; `day_changed` signal; Windows shutdown handling.
- **Files:** `services/timer_service.py`, `db/timer_repo.py`, `ui/pages/timer_page.py`, `ui/timer_bar.py`, `ui/dialogs/recovery_dialog.py`, `tests/unit/test_timer_service.py`, `tests/integration/test_timer_recovery.py`.
- **Dependencies:** none new.
- **Sequence:** (1) service with `FakeClock` tests. (2) persistence on every state change. (3) heartbeat. (4) recovery logic and tests. (5) Timer page. (6) timer bar. (7) the three dialogs. (8) shutdown and close handling.
- **Run:** `pytest -q`; manual: start the timer, kill the app from Task Manager, restart.
- **Acceptance (fake clock):** run 10 min, pause 5, run 10, stop gives exactly 1200 s; pauses are not counted; a rebuilt service from the same database after a "crash" offers time up to the last heartbeat and no later; a 46-minute inactivity gap auto-pauses and is not counted unless chosen; a backwards clock jump keeps the measured duration; a session over midnight is saved as one row; double Stop creates one row; a conflicting manual entry blocks the save with options; more than 24 h blocks the save; under 60 s asks save or discard. Manual: the recovery dialog appears with sensible numbers after a forced kill.
- **Failure modes:** counting redraws instead of reading the clock; forgetting to persist on pause; recovery counting up to "now"; the heartbeat still firing while paused; saving twice; shutdown while paused.
- **Checkpoint:** tag `m7`. Use the timer for one real study day.

### Milestone 8: Daily totals, Calendar and Dashboard

- **Objective:** every number from section G, displayed and always in agreement.
- **Features:** `daily_totals`, weekly totals, averages, streaks, session counts, task statistics in `domain/stats.py`; `stats_service`; Dashboard tiles and range selector; Calendar month grid with day detail; refresh by signals; empty states.
- **Files:** `domain/stats.py`, `services/stats_service.py`, `ui/pages/dashboard.py`, `ui/pages/calendar_page.py`, `tests/unit/test_stats.py`.
- **Dependencies:** none new.
- **Sequence:** (1) golden-value tests with a hand-calculated fixture first. (2) functions. (3) service. (4) tiles. (5) Calendar. (6) refresh wiring.
- **Run:** `pytest -q`; compare Dashboard figures with the History footer for the same range.
- **Acceptance:** golden tests for totals, averages including zero days, the first-recorded-day rule, streak with today still pending, a midnight-crossing session, and week start Monday versus Saturday; Dashboard equals History for the same range; editing a session changes the Dashboard without a restart; an empty database shows empty states, never an error.
- **Failure modes:** off-by-one at range ends; wrong week start; counting today incorrectly in averages; division by zero; month grid mistakes in months starting on different weekdays.
- **Checkpoint:** tag `m8`.

### Milestone 9: Charts and Analytics

- **Objective:** charts A to D from section G on the Dashboard and Analytics pages.
- **Features:** chart modules; lazy-loaded `mpl_canvas` widget; range controls; hover tooltips; click-through to History; Analytics tabs; Dashboard charts.
- **Files:** `charts/{style,daily_bar,weekly_trend,subject_chart,task_charts}.py`, `ui/widgets/mpl_canvas.py`, `ui/pages/analytics_page.py`, updates to `dashboard.py`, `tests/unit/test_charts.py`.
- **Dependencies:** matplotlib (already listed).
- **Sequence:** (1) chart A with tests that draw to an in-memory image and count bars. (2) embed it. (3) tooltips and click-through. (4) chart B. (5) chart C. (6) chart D. (7) Analytics page. (8) redraw wiring.
- **Run:** `python -m study_tracker`; `pytest -q`.
- **Acceptance:** chart A has exactly one bar slot per day including zero days; labels are readable at 7, 30 and 90 days; hover text is correct; chart B toggle works; chart C is sorted with subject colours; chart D shows three panels and footnotes tasks without estimates; resizing causes no overlapping labels; editing a session redraws; two years of data draws in about a second or less.
- **Failure modes:** Matplotlib backend confusion (use the Qt Agg canvas that matches PySide6); memory growth from creating a new figure every refresh (reuse the figure and clear axes); crowded tick labels; unreadable dark-theme colours; date axis versus category axis mix-ups; hover callbacks on a closed canvas.
- **Checkpoint:** tag `m9`.

### Milestone 10: CSV export, backup and restore screens, CSV import

- **Objective:** the data-ownership features of section H.
- **Features:** `export_service` for all four exports with date range, UTF-8 BOM and atomic writes; Settings Data section; manual backup without overwrite; validation report dialog; restore flow; automatic daily backup with retention; CSV import with preview and duplicate protection (last in this milestone).
- **Files:** `services/{export_service,backup_service,import_service}.py`, `ui/pages/settings_page.py`, `ui/dialogs/import_preview.py`, `docs/csv-format.md`, `tests/integration/{test_csv_roundtrip,test_backup_restore,test_import}.py`.
- **Dependencies:** none new.
- **Sequence:** (1) exporters with tests. (2) export dialog. (3) manual backup and validation. (4) restore. (5) automatic backup. (6) import parse and validate. (7) preview and commit.
- **Run:** `pytest -q`; open exports in Excel and in Pandas.
- **Acceptance:** non-ASCII notes display correctly in Excel; `pd.read_csv` loads `daily_totals.csv` with zero-days present; export then import into a fresh database reproduces identical sessions and task links; importing the same file twice adds nothing; a backup to an existing filename is refused; restore swaps the data and leaves no stale `-wal` file; restoring a corrupted or newer-version file is refused and the live database is untouched; a safety backup exists before every restore.
- **Failure modes:** Excel changing dates; commas and line breaks in notes (the `csv` module handles them, but test it); the target file open in Excel (show a clear message); restoring while the connection is open; half-written exports.
- **Checkpoint:** tag `m10`. Do a restore drill on a copy of your real database.

### Milestone 11: Reliability testing and edge cases

- **Objective:** retire every risk in section K that is not already covered.
- **Features:** a test for each risk-register row; randomised tests of `allocate_by_day`; a generator of three years of demo data for a temporary database (development only); crash and shutdown drills; keyboard-only walkthrough; startup time and memory measurements; fixes.
- **Files:** `tests/integration/test_reliability.py`, `tests/ui/*` smoke tests, `scripts/generate_demo_data.py`, `docs/RELIABILITY.md`.
- **Dependencies:** pytest-qt.
- **Sequence:** (1) walk the risk register and mark each row covered or not. (2) write the missing tests. (3) run drills by hand and record results. (4) fix what they find.
- **Run:** `pytest -q`; `python scripts/generate_demo_data.py`.
- **Acceptance:** all tests green; the manual drills (force-kill while running, sleep and wake, change the system clock, delete the database, corrupt the database, start two copies) are recorded in `docs/RELIABILITY.md` with outcomes; startup and memory figures recorded.
- **Failure modes:** tests that depend on today's date; tests sharing one database; real `sleep()` calls instead of the fake clock; slow UI tests.
- **Checkpoint:** tag `m11`: version 1 is feature-complete.

### Milestone 12: UI polish and Windows packaging

- **Objective:** a consistent interface and a double-click program that uses the correct data folder.
- **Features:** final light and dark stylesheets; bundled icons; spacing and empty states; shortcuts; app icon and About box; PyInstaller one-folder recipe that includes the stylesheet, migration `.sql` files and icons; version stamp; optional Inno Setup installer; launch smoke test.
- **Files:** `packaging/*`, `ui/theme/*`, small changes so every resource is found relative to the package, never the working directory.
- **Dependencies:** pyinstaller; Inno Setup optional.
- **Sequence:** (1) polish. (2) shortcuts and icons. (3) make resource lookup package-relative. (4) first PyInstaller build. (5) test on another Windows account or a clean machine. (6) installer if wanted.
- **Run:** `pyinstaller packaging\study_tracker.spec`, then run `dist\StudyTracker\StudyTracker.exe`.
- **Acceptance:** the executable starts without Python installed; **with `STUDY_TRACKER_HOME` unset, it opens the same `%LOCALAPPDATA%\StudyTracker\study_tracker.db` as the development version**, shown in Settings; migrations and stylesheet load from the bundle; a session can be created and survives a restart.
- **Failure modes:** data files missing from the bundle; hidden imports for Matplotlib's Qt backend; relative paths resolving against the working directory; a windowed build hiding tracebacks (send them to the log file and an error dialog); antivirus false positives.
- **Checkpoint:** tag `v1.0.0`. Back up your real database before first use.

### Milestone 13: ESP32 import

- **Objective:** import device records from a text file first, then over USB serial.
- **Features:** record parser with CRC check; subject-id mapping in Settings; review dialog with date pickers for records without a clock; import through the same preview and duplicate pipeline with `source = 'esp32'`; then the `serial_transport` module and a connect button; `docs/device-protocol.md`.
- **Files:** `services/device_import/{parser,mapping,serial_transport}.py`, `ui/dialogs/device_import_dialog.py`, `docs/device-protocol.md`, `tests/integration/test_device_import.py`, sample `.jsonl` fixture files.
- **Dependencies:** pyserial (the only new one).
- **Sequence:** (1) parser and tests from fixture files. (2) mapping. (3) review dialog. (4) import pipeline. (5) transport with a fake port in tests. (6) real port.
- **Run:** `pytest -q`; import a sample `.jsonl` file; later, connect the device.
- **Acceptance:** a fixture with good, malformed, duplicate and CRC-bad lines produces the expected counts; importing it twice adds nothing; a partial file offers the safe-import choice; a backwards `seq` warns; two epochs coexist; everything works from a file with no hardware.
- **Failure modes:** COM port busy or missing; boot messages mixed into the data stream (ignore lines that are not JSON objects); baud-rate mismatch; blocking reads freezing the window (use short timeouts polled from a Qt timer so the app stays single-threaded).
- **Checkpoint:** tag `m13`.

## K. Risk register

**The risks most likely to hurt this project are wrong time arithmetic, data landing in the wrong place, and unsafe backup or restore; each has a prevention built into the design and a test that would catch a regression.** L = likelihood, I = impact (H high, M medium, L low).

| # | Risk | L | I | Prevention in the design | How it is caught |
| --- | --- | --- | --- | --- | --- |
| 1 | Timer drifts because it counts GUI ticks | M | H | Elapsed comes from the clock, never from tick count | Fake-clock test where redraws are delayed or skipped |
| 2 | Crash during a session loses or invents time | M | H | State saved on every change; 15 s heartbeat; recovery counts only to the last heartbeat | Rebuild service from the same database and assert the recovered seconds |
| 3 | Laptop sleep inflates the elapsed time | H | H | Redraw gap over 10 s auto-pauses; gap not counted unless chosen | Fake clock jumps 46 minutes between redraws |
| 4 | System clock changed during a session | L | M | Elapsed follows the monotonic clock; discrepancy noted | Test with a backwards wall-clock jump |
| 5 | A double click saves the same session twice | M | M | Session uuid created at start, unique in the database; Stop disables on first click | Call stop twice and assert one row |
| 6 | Overlapping sessions inflate totals | M | H | One timer; overlap check on save, edit and import in one transaction | Boundary tests: touching, one-second overlap, self on edit |
| 7 | Midnight splitting off by one or parts not summing to the total | M | H | One pure function with remainder rule | Randomised test that parts always sum to the duration |
| 8 | Mixing naive and timezone-aware datetimes, or local time stored as UTC | H | H | All timestamps created from the `Clock` as UTC; one conversion helper; offset stored | Tests run under a fixed non-UTC offset such as +06:00 |
| 9 | Foreign keys silently off on some connection | M | H | One `open_db()` function sets pragmas; no other way to connect | Test that a fresh connection rejects a bad reference |
| 10 | Packaged program creates an empty database somewhere else | M | H | Only `core/paths.py` decides the folder, always absolute, never relative to the working directory; Settings shows the path; startup logs it; missing database with backups present triggers a restore offer | Run built executable with and without the override variable; compare paths |
| 11 | A plain file copy backup misses recent data (WAL) | M | H | Backup API only | Test: write rows, back up before checkpoint, restore, compare |
| 12 | Restore leaves a stale `-wal` file and corrupts the database | L | H | Close connection, remove side files, atomic rename, reopen | Restore test checks that no side files remain and `integrity_check` is `ok` |
| 13 | Migration loses data or a newer database is opened by an older app | L | H | Safety copy first; transactional migrations; refuse newer version | Migration test with sample rows; version-too-new test |
| 14 | Completing, archiving or deleting a task damages history | M | H | `RESTRICT` foreign key; delete only if unused; archive keeps sessions | Integration tests for each action |
| 15 | Two copies of the app write one database | L | H | Lock file in the data folder | Start second copy in a test or by hand |
| 16 | Excel corrupts text, or notes with commas and line breaks break the file | M | M | UTF-8 BOM, `csv` module with `newline=''`, quoting | Round-trip test with commas, quotes, newlines and Bengali text |
| 17 | Importing the same file twice duplicates sessions | M | H | Unique `uuid` and `(source, source_id)`; file hash warning; preview before commit | Import twice and compare counts |
| 18 | Two pages show different totals | M | M | One calculation module used everywhere | Test that Dashboard, Calendar and History footer agree for one fixture |
| 19 | Charts leak memory or freeze the window | M | M | Reuse one figure per canvas; redraw only when visible; lazy Matplotlib import | Measure memory after 50 refreshes in milestone 11 |
| 20 | A write fails (disk full, file locked by antivirus or a sync tool) | L | M | Errors translated to messages; timer keeps counting in memory and retries | Simulated failing repository in a test |
| 21 | The AI assistant breaks the layering or quietly changes a rule | H | M | `AGENTS.md` with the rules; one milestone at a time; tests protect the rules; read every diff | Review diffs; optional import-direction test |
| 22 | Packaged build is missing the stylesheet or migration files | M | H | Resources found relative to the package; spec file lists data files | Launch the built executable on a clean account |
| 23 | ESP32 sequence numbers restart or dates are missing | M | M | `epoch` in the key; dates assigned by you, never invented | Fixture files with reset and no-clock cases |
| 24 | The project grows beyond what you can finish | M | M | Must-have list is small; milestones are independent; future items are written down, not built | Review the scope at each tag |

### Decisions worth a second look

These are judgement calls where reasonable people would choose differently. All have defaults, and all are cheap to change if made explicit settings.

- **Midnight with pauses:** a pause that straddles midnight makes the split between the two days approximate. Storing every pause segment would make it exact but adds a table and editing complexity. The plan accepts the approximation because it is rare and small.
- **Duration-only entries on a day with timed sessions:** these cannot be overlap-checked, so a double count is possible if you record the same hour both ways. The plan warns about the day's total rather than forbidding it.
- **Heartbeat interval (15 s):** shorter loses less time after a crash but writes more often. Fifteen seconds is a safe, cheap balance on an SSD.
- **Blocking hard-delete of tasks that have sessions:** safest for history, slightly less convenient. The "unlink sessions, then delete" option is deliberately left out of version 1.
- **Streak threshold and week start:** pure preference, therefore settings.

## L. Initial implementation instructions

**Once you approve this plan, do the eight setup steps below, which take about an hour and write no application logic, then start milestone 1.** Until you approve, nothing here needs doing.

### Setup steps in VS Code

1. **Install the tools.** Python 3.12 (64-bit) from python.org, ticking "Add python.exe to PATH" (do not use the Microsoft Store version); Git for Windows; VS Code.
2. **VS Code extensions:** Python, Pylance, Ruff, and SQLite Viewer (to look inside the database file).
3. **Create the project and repository** in PowerShell:

```powershell
mkdir study-tracker
cd study-tracker
git init
code .
```

4. **Create and activate a virtual environment** in the VS Code terminal. A virtual environment is a private copy of Python for this project, so installs here cannot break anything else.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

If PowerShell refuses to run the script, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once and retry. Then press Ctrl+Shift+P, choose "Python: Select Interpreter", and pick the one inside `.venv`. The terminal prompt should start with `(.venv)`.

5. **Create the two requirements files** in the project folder.

`requirements.txt`:

```text
PySide6>=6.7,<7
matplotlib>=3.8,<4
```

`requirements-dev.txt`:

```text
-r requirements.txt
pytest>=8
pytest-qt>=4.4
ruff>=0.5
pyinstaller>=6
```

6. **Install and verify:**

```powershell
pip install -r requirements-dev.txt
python -c "import PySide6, matplotlib, sqlite3; print(PySide6.__version__, matplotlib.__version__, sqlite3.sqlite_version)"
```

Expected: three version numbers and no error.

7. **Create `.gitignore`** with these lines, then make the first commit:

```text
.venv/
__pycache__/
*.pyc
*.db
*.db-wal
*.db-shm
build/
dist/
.pytest_cache/
.ruff_cache/
logs/
```

```powershell
git add .
git commit -m "Project setup"
```

8. **Save this plan and the assistant rules.** Export this document as Markdown into `docs/PLAN.md`, and create `AGENTS.md` (below) in the project root. Commit both.

### `AGENTS.md`: standing rules for your AI coding assistant

```markdown
# Rules for AI assistants working on Study Tracker

- Read docs/PLAN.md sections D (database), E (timer) and G (statistics)
  before changing related code. The plan is the specification.
- Work on ONE milestone at a time. Do not implement later milestones.
- Layering: core <- domain <- db <- services <- ui. charts imports only
  core and domain. Never import upward. No SQL outside db/. No Qt in
  core, domain, db, services or charts.
- Timestamps are UTC ISO 8601 strings ending in Z. Durations are integer
  seconds. Get "now" only from the injected Clock, never datetime.now().
- Never edit an applied migration; add a new numbered one.
- Every business rule needs a pytest test. Run pytest and ruff check
  before saying a step is done.
- Do not add a dependency without asking first.
- No base classes, plugin systems or extra abstractions unless asked.
- Keep files small and diffs small. Explain each change in plain words.
- If a requirement is ambiguous, state a recommended default and ask.
```

### Prompt template for each milestone

```text
We are on Milestone N of docs/PLAN.md: <milestone name>.
Read sections <list the relevant ones> first.
Implement only the features listed for this milestone, in the listed
sequence, ONE step at a time. After each step tell me which command to
run and what I should see, then stop and wait for me.
Write the tests listed under Acceptance before or together with the code.
Do not touch files outside the milestone's file list without asking.
```

### What I need from you

1. Approve the plan, or tell me what to change. The four questions in the summary have defaults, so silence means "use the defaults".
2. When you approve, I will write the detailed implementation guide for milestone 1 (the contents of the `core` modules and the first tests), and we will go one milestone at a time from there.
