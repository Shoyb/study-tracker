"""Small undo journal service."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any

from study_tracker.db import journal_repo
from study_tracker.services.undo import adapters


class JournalService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @contextmanager
    def action(self, summary: str, created_at_utc: str) -> Iterator[Callable[..., None]]:
        """Keep one user action and all its journal rows in one savepoint."""
        group_id = str(uuid.uuid4())
        savepoint = f"undo_{uuid.uuid4().hex}"
        self._conn.execute(f"SAVEPOINT {savepoint}")
        try:
            journal_repo.clear_redo(self._conn)

            def record(
                entity_type: str,
                entity_id: int,
                operation: str,
                before: dict[str, Any] | None,
                after: dict[str, Any] | None,
            ) -> None:
                journal_repo.append(
                    self._conn,
                    group_id=group_id,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    action=operation,
                    summary=summary,
                    before_json=before,
                    after_json=after,
                    created_at_utc=created_at_utc,
                )

            yield record
            self._conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        except Exception:
            self._conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            self._conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            raise

    def undo(self, now_utc: str) -> str | None:
        group_id = journal_repo.latest_group(self._conn, undone=False)
        if group_id is None:
            return None
        with self._atomic("undo"):
            entries = journal_repo.entries_for_group(
                self._conn, group_id, newest_first=True
            )
            for entry in entries:
                current = adapters.snapshot(self._conn, entry.entity_type, entry.entity_id)
                expected = json.loads(entry.after_json) if entry.after_json else None
                if current != expected:
                    raise RuntimeError(
                        f"Cannot undo '{entry.summary}': {entry.entity_type} "
                        f"{entry.entity_id} changed outside the journal."
                    )
                if entry.action == "create":
                    adapters.delete(self._conn, entry.entity_type, entry.entity_id)
                elif entry.action == "delete":
                    adapters.restore(
                        self._conn, entry.entity_type, json.loads(entry.before_json or "{}")
                    )
                else:
                    adapters.apply(
                        self._conn, entry.entity_type, json.loads(entry.before_json or "{}")
                    )
            journal_repo.mark_group_undone(self._conn, group_id, now_utc)
        return entries[0].summary if entries else None

    def redo(self, now_utc: str) -> str | None:
        group_id = journal_repo.latest_group(self._conn, undone=True)
        if group_id is None:
            return None
        with self._atomic("redo"):
            entries = journal_repo.entries_for_group(
                self._conn, group_id, newest_first=False
            )
            for entry in entries:
                current = adapters.snapshot(self._conn, entry.entity_type, entry.entity_id)
                expected = json.loads(entry.before_json) if entry.before_json else None
                if current != expected:
                    raise RuntimeError(
                        f"Cannot redo '{entry.summary}': {entry.entity_type} "
                        f"{entry.entity_id} changed outside the journal."
                    )
                if entry.action == "create":
                    adapters.restore(
                        self._conn, entry.entity_type, json.loads(entry.after_json or "{}")
                    )
                elif entry.action == "delete":
                    adapters.delete(self._conn, entry.entity_type, entry.entity_id)
                else:
                    adapters.apply(
                        self._conn, entry.entity_type, json.loads(entry.after_json or "{}")
                    )
            journal_repo.mark_group_undone(self._conn, group_id, None)
        return entries[0].summary if entries else None

    def undo_through(self, entry_id: int, now_utc: str) -> str | None:
        target = journal_repo.get_by_id(self._conn, entry_id)
        if target is None or target.undone_at_utc is not None:
            return None
        with self._atomic("undo_to"):
            while (group_id := journal_repo.latest_group(self._conn, undone=False)) is not None:
                summary = self.undo(now_utc)
                if group_id == target.group_id:
                    return summary
        return None

    def purge(self, now_utc: str, *, keep_entries: int = 500, keep_days: int = 30) -> int:
        now = datetime.strptime(now_utc, "%Y-%m-%dT%H:%M:%SZ")
        before = (now - timedelta(days=keep_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return journal_repo.purge(
            self._conn, keep_entries=keep_entries, before_utc=before
        )

    @contextmanager
    def _atomic(self, name: str) -> Iterator[None]:
        savepoint = f"{name}_{uuid.uuid4().hex}"
        self._conn.execute(f"SAVEPOINT {savepoint}")
        try:
            yield
            self._conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        except Exception:
            self._conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            self._conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            raise

    def record(
        self,
        *,
        group_id: str,
        entity_type: str,
        entity_id: int,
        action: str,
        summary: str,
        before_json=None,
        after_json=None,
        created_at_utc: str,
    ) -> journal_repo.ChangeEntry:
        return journal_repo.append(
            self._conn,
            group_id=group_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            summary=summary,
            before_json=before_json,
            after_json=after_json,
            created_at_utc=created_at_utc,
        )

    def history(self, limit: int = 50):
        return journal_repo.list_recent(self._conn, limit=limit)
