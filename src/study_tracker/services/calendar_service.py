"""Calendar data service for notes and events."""

from __future__ import annotations

import sqlite3
from datetime import date

from study_tracker.core.errors import NotFoundError, ValidationError
from study_tracker.db import calendar_repo, tasks_repo
from study_tracker.db.calendar_repo import CalendarItem
from study_tracker.services.undo.adapters import snapshot
from study_tracker.services.undo.journal import JournalService


def _validate(
    *,
    kind: str,
    title: str,
    notes: str,
    local_date: str,
    start_time: str | None,
    end_time: str | None,
    task_id: int | None,
) -> tuple[str, str]:
    if kind not in {"note", "event"}:
        raise ValidationError("Calendar item must be a note or event.")
    title = title.strip()
    notes = notes.strip()
    if not title or len(title) > 120:
        raise ValidationError("Title must be between 1 and 120 characters.")
    if len(notes) > 2000:
        raise ValidationError("Notes cannot exceed 2000 characters.")
    try:
        date.fromisoformat(local_date)
    except ValueError as exc:
        raise ValidationError("Date must be a valid YYYY-MM-DD date.") from exc
    if kind == "note" and (start_time is not None or end_time is not None):
        raise ValidationError("Notes cannot have a time.")
    start_minutes = _minutes(start_time) if start_time is not None else None
    end_minutes = _minutes(end_time) if end_time is not None else None
    if end_minutes is not None and start_minutes is None:
        raise ValidationError("An end time requires a start time.")
    if start_minutes is not None and end_minutes is not None and end_minutes <= start_minutes:
        raise ValidationError("End time must be later than start time.")
    return title, notes


def _minutes(value: str) -> int:
    try:
        hours_text, minutes_text = value.split(":")
        hours, minutes = int(hours_text), int(minutes_text)
    except (ValueError, TypeError) as exc:
        raise ValidationError("Time must use HH:MM format.") from exc
    if not 0 <= hours <= 23 or not 0 <= minutes <= 59:
        raise ValidationError("Time must be between 00:00 and 23:59.")
    return hours * 60 + minutes


def _create(
    conn: sqlite3.Connection,
    *,
    kind: str,
    title: str,
    notes: str,
    local_date: str,
    start_time: str | None,
    end_time: str | None,
    task_id: int | None,
    color_hex: str | None,
    created_at: str,
) -> CalendarItem:
    title, notes = _validate(
        kind=kind,
        title=title,
        notes=notes,
        local_date=local_date,
        start_time=start_time,
        end_time=end_time,
        task_id=task_id,
    )
    if task_id is not None and tasks_repo.get_by_id(conn, task_id) is None:
        raise NotFoundError(f"Task {task_id} not found.")
    summary = f"Add calendar {kind}"
    with JournalService(conn).action(summary, created_at) as record:
        item = calendar_repo.create(
            conn,
            kind=kind,
            title=title,
            notes=notes,
            local_date=local_date,
            start_time=start_time,
            end_time=end_time,
            task_id=task_id,
            color_hex=color_hex,
            created_at=created_at,
        )
        record("calendar_item", item.id, "create", None, snapshot(conn, "calendar_item", item.id))
    return item


def add_note(
    conn: sqlite3.Connection, *, title: str, notes: str, local_date: str, created_at: str
) -> CalendarItem:
    return _create(
        conn,
        kind="note",
        title=title,
        notes=notes,
        local_date=local_date,
        start_time=None,
        end_time=None,
        task_id=None,
        color_hex=None,
        created_at=created_at,
    )


def add_event(
    conn: sqlite3.Connection,
    *,
    title: str,
    notes: str,
    local_date: str,
    start_time: str | None,
    end_time: str | None,
    created_at: str,
    task_id: int | None = None,
    color_hex: str | None = None,
) -> CalendarItem:
    return _create(
        conn,
        kind="event",
        title=title,
        notes=notes,
        local_date=local_date,
        start_time=start_time,
        end_time=end_time,
        task_id=task_id,
        color_hex=color_hex,
        created_at=created_at,
    )


def update(
    conn: sqlite3.Connection,
    item_id: int,
    *,
    title: str,
    notes: str,
    local_date: str,
    start_time: str | None,
    end_time: str | None,
    task_id: int | None,
    color_hex: str | None,
    is_done: bool,
    updated_at: str,
) -> CalendarItem:
    existing = calendar_repo.get_by_id(conn, item_id)
    if existing is None:
        raise NotFoundError(f"Calendar item {item_id} not found.")
    title, notes = _validate(
        kind=existing.kind,
        title=title,
        notes=notes,
        local_date=local_date,
        start_time=start_time,
        end_time=end_time,
        task_id=task_id,
    )
    if task_id is not None and tasks_repo.get_by_id(conn, task_id) is None:
        raise NotFoundError(f"Task {task_id} not found.")
    before = snapshot(conn, "calendar_item", item_id)
    with JournalService(conn).action("Edit calendar item", updated_at) as record:
        calendar_repo.update(
            conn,
            item_id,
            title=title,
            notes=notes,
            local_date=local_date,
            start_time=start_time,
            end_time=end_time,
            task_id=task_id,
            color_hex=color_hex,
            is_done=is_done,
            updated_at=updated_at,
        )
        record("calendar_item", item_id, "update", before, snapshot(conn, "calendar_item", item_id))
    updated = calendar_repo.get_by_id(conn, item_id)
    assert updated is not None
    return updated


def delete(conn: sqlite3.Connection, item_id: int, now_utc: str) -> None:
    item = calendar_repo.get_by_id(conn, item_id)
    if item is None:
        raise NotFoundError(f"Calendar item {item_id} not found.")
    before = snapshot(conn, "calendar_item", item_id)
    with JournalService(conn).action("Delete calendar item", now_utc) as record:
        calendar_repo.delete(conn, item_id)
        record("calendar_item", item_id, "delete", before, None)


def get_items_for_date(
    conn: sqlite3.Connection, local_date: str, cutoff_minutes: int = 180
) -> list[CalendarItem]:
    return calendar_repo.get_for_date(conn, local_date, cutoff_minutes)


def get_items_for_range(
    conn: sqlite3.Connection, date_from: str, date_to: str
) -> list[CalendarItem]:
    return calendar_repo.get_for_range(conn, date_from, date_to)
