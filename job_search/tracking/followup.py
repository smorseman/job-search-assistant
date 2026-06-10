"""Follow-up engine — surfaces due actions in the daily report."""

from __future__ import annotations

import logging
from datetime import date

from job_search.db import get_db
from job_search.models import AppState

logger = logging.getLogger(__name__)

# Applied with no acknowledgment after this many days → ghosted auto-flag
GHOSTED_DAYS = 30


class FollowUpEngine:
    def run(self) -> list[dict]:
        """Return list of due follow-up actions for today's report."""
        today = date.today().isoformat()
        actions = []

        with get_db() as db:
            # Auto-flag ghosted applications
            self._auto_flag_ghosted(db, today)

            # Fetch overdue follow-up items
            rows = db.execute(
                """
                SELECT fq.*, j.company, j.title, j.app_state, j.apply_url
                FROM followup_queue fq
                JOIN jobs j ON j.canonical_job_id = fq.canonical_job_id
                WHERE fq.resolved = 0
                  AND fq.due_date <= ?
                ORDER BY fq.due_date ASC
                LIMIT 50
                """,
                (today,),
            ).fetchall()

            for row in rows:
                actions.append(dict(row))

        return actions

    def _auto_flag_ghosted(self, db, today: str) -> None:
        """Move applied → ghosted if GHOSTED_DAYS have passed with no progress."""
        from datetime import datetime, timedelta
        cutoff = (date.today() - __import__("datetime").timedelta(days=GHOSTED_DAYS)).isoformat()

        stale = db.execute(
            """
            SELECT canonical_job_id FROM jobs
            WHERE app_state = 'applied'
              AND updated_at <= ?
            """,
            (cutoff + "T00:00:00",),
        ).fetchall()

        for row in stale:
            job_id = row["canonical_job_id"]
            db.execute(
                "UPDATE jobs SET app_state = 'ghosted', updated_at = datetime('now') WHERE canonical_job_id = ?",
                (job_id,),
            )
            db.execute(
                "INSERT INTO app_transitions (canonical_job_id, from_state, to_state, note) VALUES (?, 'applied', 'ghosted', ?)",
                (job_id, f"Auto-flagged: {GHOSTED_DAYS} days post-apply with no response"),
            )
            db.execute(
                """
                INSERT INTO followup_queue (canonical_job_id, action_type, due_date, note)
                VALUES (?, 'check_status', ?, 'Application ghosted — decide whether to follow up or close')
                """,
                (job_id, today),
            )
            logger.info("Auto-ghosted %s", job_id)

    def mark_resolved(self, followup_id: int) -> None:
        with get_db() as db:
            db.execute(
                "UPDATE followup_queue SET resolved = 1, resolved_at = datetime('now') WHERE id = ?",
                (followup_id,),
            )
