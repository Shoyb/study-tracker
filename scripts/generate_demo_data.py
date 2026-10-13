"""Generate three years of disposable demo study data.

Run: ``python scripts/generate_demo_data.py --output C:\\temp\\study_demo.db``.
The script refuses to overwrite an existing database.
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from study_tracker.db.connection import get_connection  # noqa: E402
from study_tracker.db.migrate import run_migrations  # noqa: E402
from study_tracker.services import session_service, task_service  # noqa: E402


def generate(output: Path, *, years: int = 3, seed: int = 42) -> None:
    """Create a deterministic demo database without overwriting user data."""
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite existing database: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    conn = get_connection(output)
    try:
        run_migrations(conn, output)
        created = "2026-01-01T00:00:00Z"
        tasks = [
            task_service.create(
                conn,
                subject_id=subject_id,
                title=f"Demo task {subject_id}",
                created_at=created,
            )
            for subject_id in range(1, 6)
        ]
        current = date(2023, 1, 1)
        end = current + timedelta(days=365 * years)
        while current < end:
            if rng.random() < 0.7:
                subject_id = rng.randint(1, 5)
                session_service.add_manual_duration(
                    conn,
                    subject_id=subject_id,
                    task_id=tasks[subject_id - 1].id if rng.random() < 0.65 else None,
                    local_date=current.isoformat(),
                    duration_secs=rng.randint(15, 180) * 60,
                    notes="Generated demo data",
                    created_at=created,
                )
            current += timedelta(days=1)
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a Study Tracker demo database.")
    parser.add_argument("--output", type=Path, required=True, help="New .db file to create")
    parser.add_argument("--years", type=int, default=3, help="Years of daily data (default: 3)")
    args = parser.parse_args()
    generate(args.output, years=args.years)
    print(f"Created demo database: {args.output}")


if __name__ == "__main__":
    main()
