# Study Tracker CSV format

All CSV files use UTF-8 with a BOM, comma separators, and integer seconds.

- `sessions.csv` is importable. `session_uuid` avoids duplicates; timed entries have UTC `start_utc` and `end_utc`, while duration-only entries leave both blank.
- `tasks.csv` is importable. `task_uuid` is the stable task identity; `time_spent_seconds` and `session_count` are derived fields and ignored on import.
- `daily_totals.csv` has one row for every date in the selected range, including zero-study days.
- `subject_summary.csv` lists allocated time, session count, and a share of selected time for each subject.
- `daily_by_subject.csv` is long-format data (`date`, `subject`, `seconds`) intended for pivot tables.

Import tasks before sessions when moving data between databases. Imports validate all rows before saving and ignore rows already present by UUID or source identity.
