"""Application state machine — valid transitions and transition logging."""

from __future__ import annotations

from sqlite3 import Connection

from job_search.models import AppState

# Valid transitions: current_state → set of allowed next states
VALID_TRANSITIONS: dict[str, set[str]] = {
    AppState.DISCOVERED.value:   {AppState.PRESENTED.value},
    AppState.PRESENTED.value:    {AppState.SELECTED.value, AppState.DISCOVERED.value},
    AppState.SELECTED.value:     {AppState.APPLIED.value, AppState.PRESENTED.value},
    AppState.APPLIED.value:      {AppState.ACKNOWLEDGED.value, AppState.SCREEN.value, AppState.REJECTED.value, AppState.GHOSTED.value},
    AppState.ACKNOWLEDGED.value: {AppState.SCREEN.value, AppState.REJECTED.value, AppState.GHOSTED.value},
    AppState.SCREEN.value:       {AppState.INTERVIEW.value, AppState.REJECTED.value},
    AppState.INTERVIEW.value:    {AppState.OFFER.value, AppState.REJECTED.value},
    AppState.OFFER.value:        {AppState.REJECTED.value},    # declined offer
    AppState.REJECTED.value:     set(),                        # terminal
    AppState.GHOSTED.value:      {AppState.SCREEN.value},      # late response
}


def advance_state(
    db: Connection,
    canonical_job_id: str,
    to_state: str,
    note: str | None = None,
) -> bool:
    """
    Transition a job to a new state.  Returns True on success, False if invalid.
    Records the transition in app_transitions.
    """
    row = db.execute(
        "SELECT app_state FROM jobs WHERE canonical_job_id = ?",
        (canonical_job_id,),
    ).fetchone()

    if not row:
        return False

    current = row["app_state"]
    allowed = VALID_TRANSITIONS.get(current, set())

    if to_state not in allowed:
        return False

    db.execute(
        "UPDATE jobs SET app_state = ?, updated_at = datetime('now') WHERE canonical_job_id = ?",
        (to_state, canonical_job_id),
    )
    db.execute(
        "INSERT INTO app_transitions (canonical_job_id, from_state, to_state, note) VALUES (?, ?, ?, ?)",
        (canonical_job_id, current, to_state, note),
    )

    # Set applied_date on Sheet-mirror when moving to applied
    if to_state == AppState.APPLIED.value:
        from datetime import date
        db.execute(
            "UPDATE jobs SET posted_date = coalesce(posted_date, ?), updated_at = datetime('now') WHERE canonical_job_id = ?",
            (date.today().isoformat(), canonical_job_id),
        )
        _schedule_followup(db, canonical_job_id)

    return True


def _schedule_followup(db: Connection, canonical_job_id: str) -> None:
    from datetime import date, timedelta
    # Surface in report if no acknowledgment after 10 business days (~14 calendar)
    due = (date.today() + timedelta(days=14)).isoformat()
    db.execute(
        "INSERT INTO followup_queue (canonical_job_id, action_type, due_date, note) VALUES (?, 'check_status', ?, ?)",
        (canonical_job_id, due, "10-business-day post-apply follow-up window"),
    )
