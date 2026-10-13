# Study Tracker

Study Tracker is a local-first desktop app made specifically for Bangladeshi students preparing for undergraduate admission. It helps organize subject study, admission-exam practice, daily targets, and study-time records in one place. It can also be used for school, university courses, professional learning, or personal projects.

## Features

- Stopwatch, Pomodoro focus/break cycles, and a standalone countdown.
- Manual sessions with exact times or duration only, including sessions whose subject was not tracked.
- Split a "No subject" session among subjects using exact durations or relative weights; optionally leave time unassigned.
- Tasks, priorities, due dates, estimates, and subject organization.
- Exam plans and results with configurable categories, levels, and scoring schemes.
- Daily plans, optional weekday study-hour and exam-count baselines, and per-subject daily targets.
- Dashboard, calendar, history, charts, analytics, and editable records.
- Local SQLite storage, automatic and manual backups, restore validation, and CSV import/export.

## Requirements

- Windows 10 or 11, 64-bit, for the packaged build.
- Python 3.12 or newer for running from source.
- The app uses PySide6 and Matplotlib. Their dependencies are installed from the project requirements.

## Run from source

From PowerShell in the project directory:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m study_tracker
```

The app opens with a local database. For development or testing, set `STUDY_TRACKER_HOME` to a temporary directory before launching so test data stays separate from your normal profile.

## Data and privacy

On Windows, the database is stored per Windows user at:

```text
%LOCALAPPDATA%\StudyTracker\study_tracker.db
```

Backups and logs are stored beside it. The app does not provide accounts, cloud sync, or automatic sharing. Another person or computer gets its own database. To transfer data, create and restore a validated SQLite backup, or export/import CSV files. Import tasks before sessions when moving linked records. See [docs/csv-format.md](docs/csv-format.md) for the CSV columns.

## Development checks

Install development tools and run the checks:

```powershell
python -m pip install -r requirements-dev.txt
ruff check .
pytest -q
```

## Release build

On Windows, run the release script from PowerShell:

```powershell
.\packaging\build.ps1
```

It runs Ruff and pytest, creates the PyInstaller one-folder bundle, then writes a versioned ZIP and SHA-256 checksum under `release/`. The release folder is not the data folder; users' databases remain under `%LOCALAPPDATA%\StudyTracker`.

The release script stops if tests or lint fail. `-SkipTests` is available only for an intentional troubleshooting build; complete the manual checks in [docs/RELIABILITY.md](docs/RELIABILITY.md) before publishing a release.

## License

Study Tracker is licensed under the MIT License. See [LICENSE](LICENSE).
