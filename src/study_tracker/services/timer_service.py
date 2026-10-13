"""Timer service – core stopwatch logic, persistence, and crash recovery."""

from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta

from study_tracker.core.errors import ConflictError, ValidationError
from study_tracker.db import sessions_repo, subjects_repo, tasks_repo, timer_state_repo
from study_tracker.db.sessions_repo import Session
from study_tracker.db.timer_state_repo import TimerState
from study_tracker.domain.validation import validate_duration_secs

log = logging.getLogger(__name__)


class TimerService:
    """Manages the study stopwatch.

    Guarantees:
    - Elapsed time is measured using monotonic clock while open.
    - Timer state is persisted to SQLite on every state change and heartbeat.
    - Pauses are not counted.
    - Recovered time after crash stops at the last heartbeat.
    """

    def __init__(self, conn: sqlite3.Connection, clock) -> None:
        self._conn = conn
        self._clock = clock

        # In-memory timer state
        self._is_active: bool = False
        self._is_paused: bool = False
        self._subject_id: int = 1
        self._task_id: int | None = None
        self._notes: str = ""
        self._start_utc: str = ""
        self._last_heartbeat: str = ""
        self._accumulated_secs: int = 0
        self._segment_start_mono: float = 0.0
        self._last_tick_mono: float = 0.0
        self._last_tick_wall: float = 0.0

    @property
    def is_active(self) -> bool:
        return self._is_active

    @property
    def is_paused(self) -> bool:
        return self._is_paused

    @property
    def is_running(self) -> bool:
        return self._is_active and not self._is_paused

    @property
    def subject_id(self) -> int:
        return self._subject_id

    @property
    def task_id(self) -> int | None:
        return self._task_id

    @property
    def notes(self) -> str:
        return self._notes

    @property
    def start_utc(self) -> str:
        return self._start_utc

    def set_notes(self, notes: str) -> None:
        self._notes = notes
        if self._is_active:
            self._persist()

    def elapsed_seconds(self) -> int:
        """Return the active elapsed time in seconds."""
        if not self._is_active:
            return 0
        if self._is_paused:
            return self._accumulated_secs
        current_segment = int(self._clock.monotonic() - self._segment_start_mono)
        return self._accumulated_secs + max(0, current_segment)

    def start(self, subject_id: int, task_id: int | None = None, notes: str = "") -> None:
        """Start a new timer."""
        if self._is_active:
            subj = subjects_repo.get_by_id(self._conn, self._subject_id)
            name = subj.name if subj else "another subject"
            raise ConflictError(f"A timer is already running for {name}.")

        if subjects_repo.get_by_id(self._conn, subject_id) is None:
            raise ValidationError(f"Subject {subject_id} not found.")

        now_utc = self._clock.now_utc()
        mono_now = self._clock.monotonic()

        self._is_active = True
        self._is_paused = False
        self._subject_id = subject_id
        self._task_id = task_id
        self._notes = notes
        self._start_utc = now_utc
        self._last_heartbeat = now_utc
        self._accumulated_secs = 0
        self._segment_start_mono = mono_now
        self._last_tick_mono = mono_now
        self._last_tick_wall = self._wall_timestamp()

        self._persist()
        log.info("Timer started for subject %d.", subject_id)

    def pause(self) -> None:
        """Pause the running timer."""
        if not self._is_active or self._is_paused:
            return

        mono_now = self._clock.monotonic()
        segment = int(mono_now - self._segment_start_mono)
        self._accumulated_secs += max(0, segment)
        self._is_paused = True
        self._last_heartbeat = self._clock.now_utc()

        self._persist()
        log.info("Timer paused. Accumulated seconds: %d.", self._accumulated_secs)

    def resume(self) -> None:
        """Resume a paused timer."""
        if not self._is_active or not self._is_paused:
            return

        mono_now = self._clock.monotonic()
        self._is_paused = False
        self._segment_start_mono = mono_now
        self._last_tick_mono = mono_now
        self._last_tick_wall = self._wall_timestamp()
        self._last_heartbeat = self._clock.now_utc()

        self._persist()
        log.info("Timer resumed.")

    def heartbeat(self) -> None:
        """Write 15-second heartbeat while actively running."""
        if not self.is_running:
            return
        self._last_heartbeat = self._clock.now_utc()
        self._persist()

    def check_inactivity_gap(self) -> int | None:
        """Check for gaps caused by computer sleep or freeze.

        Returns gap seconds if gap > 10 seconds, else None.
        """
        if not self.is_running:
            return None

        mono_now = self._clock.monotonic()
        mono_gap = mono_now - self._last_tick_mono
        wall_now = self._wall_timestamp()
        wall_gap = wall_now - self._last_tick_wall

        if max(mono_gap, wall_gap) > 10.0:
            # Bank time only to the last redraw. The interval after it is an
            # unknown sleep/freeze gap and must never be silently counted.
            self._accumulated_secs += max(0, int(self._last_tick_mono - self._segment_start_mono))
            self._is_paused = True
            self._last_heartbeat = self._clock.now_utc()
            self._last_tick_mono = mono_now
            self._last_tick_wall = wall_now
            self._persist()
            gap_secs = int(max(mono_gap, wall_gap))
            log.warning("Detected inactivity gap of %d seconds. Timer auto-paused.", gap_secs)
            return gap_secs

        self._last_tick_mono = mono_now
        self._last_tick_wall = wall_now
        return None

    def stop(self, utc_offset_mins: int = 0) -> Session:
        """Stop and save the current timer session."""
        if not self._is_active:
            raise ValidationError("No timer is active.")

        duration = self.elapsed_seconds()
        if duration <= 0:
            duration = 1  # Minimum 1 second for database constraint
        validate_duration_secs(duration)

        now_utc = self._clock.now_utc()
        start_utc = self._start_utc
        end_utc = now_utc

        # Handle backward wall-clock jump or span shorter than duration
        s_dt = datetime.strptime(start_utc, "%Y-%m-%dT%H:%M:%SZ")
        e_dt = datetime.strptime(end_utc, "%Y-%m-%dT%H:%M:%SZ")
        span = int((e_dt - s_dt).total_seconds())

        if span < duration or e_dt <= s_dt:
            # Duration wins
            e_dt = s_dt + timedelta(seconds=duration)
            end_utc = e_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Overlap check
        overlapping = sessions_repo.find_overlapping(
            self._conn, start_utc=start_utc, end_utc=end_utc
        )
        if overlapping:
            conflict = overlapping[0]
            raise ConflictError(
                f"Session overlaps with existing session {conflict.id} "
                f"({conflict.start_utc} to {conflict.end_utc})."
            )

        # Derive local date
        s_dt_utc = datetime.strptime(start_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        local_date = (s_dt_utc + timedelta(minutes=utc_offset_mins)).strftime("%Y-%m-%d")

        sess_uuid = str(uuid.uuid4())
        sess_id = sessions_repo.insert(
            self._conn,
            uuid=sess_uuid,
            subject_id=self._subject_id,
            task_id=self._task_id,
            local_date=local_date,
            start_utc=start_utc,
            end_utc=end_utc,
            duration_secs=duration,
            session_type="timer",
            notes=self._notes.strip(),
            utc_offset_mins=utc_offset_mins,
            created_at=now_utc,
        )

        # If task was todo, transition to in_progress
        if self._task_id:
            task = tasks_repo.get_by_id(self._conn, self._task_id)
            if task and task.status == "todo":
                tasks_repo.update(
                    self._conn,
                    task.id,
                    subject_id=task.subject_id,
                    title=task.title,
                    status="in_progress",
                    priority=task.priority,
                    archived=task.archived,
                    due_date=task.due_date,
                    estimate_secs=task.estimate_secs,
                    notes=task.notes,
                    completed_at=None,
                )

        self._reset()
        timer_state_repo.clear(self._conn)

        sess = sessions_repo.get_by_id(self._conn, sess_id)
        assert sess is not None
        log.info("Timer stopped and session saved: id=%d duration=%ds.", sess_id, duration)
        return sess

    def discard(self) -> None:
        """Discard the current running or paused session without saving."""
        self._reset()
        timer_state_repo.clear(self._conn)
        log.info("Timer session discarded.")

    def _reset(self) -> None:
        self._is_active = False
        self._is_paused = False
        self._subject_id = 1
        self._task_id = None
        self._notes = ""
        self._start_utc = ""
        self._last_heartbeat = ""
        self._accumulated_secs = 0
        self._segment_start_mono = 0.0

    def _wall_timestamp(self) -> float:
        """Read wall time from the injected clock, never from the system directly."""
        value = datetime.strptime(self._clock.now_utc(), "%Y-%m-%dT%H:%M:%SZ")
        return value.replace(tzinfo=UTC).timestamp()

    def _persist(self) -> None:
        state = TimerState(
            subject_id=self._subject_id,
            task_id=self._task_id,
            start_utc=self._start_utc,
            last_heartbeat=self._last_heartbeat,
            paused_secs=self._accumulated_secs,
            is_paused=self._is_paused,
            pause_start=self._last_heartbeat if self._is_paused else None,
            notes=self._notes,
        )
        timer_state_repo.save(self._conn, state)

    # ── Recovery Methods ──────────────────────────────────────────

    def load_persisted_state(self) -> TimerState | None:
        return timer_state_repo.load(self._conn)

    def recover_as_paused(self, state: TimerState) -> None:
        """Restore crash state into memory as paused so the user can continue or stop."""
        self._is_active = True
        self._is_paused = True
        self._subject_id = state.subject_id
        self._task_id = state.task_id
        self._notes = state.notes
        self._start_utc = state.start_utc
        self._last_heartbeat = state.last_heartbeat

        # Calculate recovered seconds:
        # Banked seconds + (last heartbeat - start_utc) if was running,
        # never later than last heartbeat!
        if state.is_paused:
            self._accumulated_secs = state.paused_secs
        else:
            s_dt = datetime.strptime(state.start_utc, "%Y-%m-%dT%H:%M:%SZ")
            h_dt = datetime.strptime(state.last_heartbeat, "%Y-%m-%dT%H:%M:%SZ")
            heartbeat_span = max(0, int((h_dt - s_dt).total_seconds()))
            self._accumulated_secs = state.paused_secs + heartbeat_span

        self._persist()

    def recover_and_save(self, state: TimerState, utc_offset_mins: int = 0) -> Session:
        """Save recovered session stopping at last_heartbeat."""
        if state.is_paused:
            dur = max(1, state.paused_secs)
            end_utc = state.last_heartbeat
        else:
            s_dt = datetime.strptime(state.start_utc, "%Y-%m-%dT%H:%M:%SZ")
            h_dt = datetime.strptime(state.last_heartbeat, "%Y-%m-%dT%H:%M:%SZ")
            dur = max(1, state.paused_secs + int((h_dt - s_dt).total_seconds()))
            end_utc = state.last_heartbeat

        # Derive local date
        s_dt_utc = datetime.strptime(state.start_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        local_date = (s_dt_utc + timedelta(minutes=utc_offset_mins)).strftime("%Y-%m-%d")

        sess_uuid = str(uuid.uuid4())
        sess_id = sessions_repo.insert(
            self._conn,
            uuid=sess_uuid,
            subject_id=state.subject_id,
            task_id=state.task_id,
            local_date=local_date,
            start_utc=state.start_utc,
            end_utc=end_utc,
            duration_secs=dur,
            session_type="timer",
            notes=state.notes.strip(),
            utc_offset_mins=utc_offset_mins,
            created_at=self._clock.now_utc(),
        )

        timer_state_repo.clear(self._conn)
        sess = sessions_repo.get_by_id(self._conn, sess_id)
        assert sess is not None
        return sess
