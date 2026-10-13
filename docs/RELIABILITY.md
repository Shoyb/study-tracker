# Reliability verification

Automated coverage includes timer recovery, pause handling, backward wall-clock jumps, sleep-gap exclusion, duplicate stops, database constraints, backups/restores, CSV round trips, duplicate imports, and randomized midnight allocation.

## Manual drills to perform before a release

| Drill | Expected result | Status |
| --- | --- | --- |
| Force-kill while a timer runs, then reopen | Recovery offers only time through the last heartbeat. | Pending manual run |
| Sleep or close the laptop while a timer runs | Timer pauses at the last redraw; the gap is not recorded. | Pending manual run |
| Change the system clock while a timer runs | Recorded duration follows monotonic elapsed time. | Covered by automated test |
| Rename or delete the database while backups exist | Startup creates a fresh database and logs that backups are available. | Pending manual run |
| Attempt to restore a corrupt backup | Restore is refused and the live database remains unchanged. | Covered by automated test |
| Launch a second copy | The second process reports that Study Tracker is already running. | Pending manual run |
| Keyboard-only pass | Sidebar, buttons, and dialogs are reachable in a sensible Tab order. | Pending manual run |

## Measurements

Run `python scripts/generate_demo_data.py --output C:\temp\study_demo.db`, open it in the app, and record startup time and memory on the target computer here before release. Measurements are machine-specific, so no fabricated figures are recorded.
