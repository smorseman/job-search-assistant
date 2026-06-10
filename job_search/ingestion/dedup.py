"""Dedup and repost detection.

Dedup by canonical_job_id (exact).
Repost detection: normalized JD hash + fuzzy match on title + company + location.
"""

from __future__ import annotations

import logging
from sqlite3 import Connection

from rapidfuzz import fuzz

from job_search.models import AppState, CanonicalJob

logger = logging.getLogger(__name__)

FUZZY_REPOST_THRESHOLD = 92   # % similarity to flag as repost
TITLE_COMPANY_LOC_THRESHOLD = 88


class Deduplicator:
    def __init__(self, db: Connection):
        self.db = db

    def upsert(self, job: CanonicalJob) -> tuple[bool, bool]:
        """
        Insert or update a job record.

        Returns (is_new, is_repost).
        - is_new=True  → first time this canonical_job_id has been seen
        - is_repost=True → different canonical_job_id but looks like the same role
        """
        existing = self.db.execute(
            "SELECT canonical_job_id, app_state FROM jobs WHERE canonical_job_id = ?",
            (job.canonical_job_id,),
        ).fetchone()

        if existing:
            # Known job — update last_seen and potentially re-score
            self.db.execute(
                "UPDATE jobs SET last_seen = datetime('now'), updated_at = datetime('now') WHERE canonical_job_id = ?",
                (job.canonical_job_id,),
            )
            # If the candidate already applied to this and it reappeared → follow-up signal
            if existing["app_state"] in (AppState.APPLIED.value, AppState.SELECTED.value):
                logger.info(
                    "Re-appeared posting for already-applied job %s — flagging follow-up",
                    job.canonical_job_id,
                )
                self._enqueue_followup(job.canonical_job_id, "reappeared_after_apply")
            return False, False

        # Check for repost (same role, different posting)
        is_repost = self._detect_repost(job)

        # Insert new record
        d = job.to_db_dict()
        cols = ", ".join(d.keys())
        placeholders = ", ".join(["?"] * len(d))
        self.db.execute(
            f"INSERT INTO jobs ({cols}) VALUES ({placeholders})",
            list(d.values()),
        )
        return True, is_repost

    def _detect_repost(self, job: CanonicalJob) -> bool:
        """
        Compare against recent postings from the same company.
        Returns True if this looks like a duplicate role posted fresh.
        """
        # Hash-based exact match on normalized JD
        if job.jd_content_hash:
            hash_match = self.db.execute(
                "SELECT canonical_job_id FROM jobs WHERE jd_content_hash = ? AND company = ? LIMIT 1",
                (job.jd_content_hash, job.company),
            ).fetchone()
            if hash_match:
                logger.info("Repost detected via JD hash: %s → %s", job.canonical_job_id, hash_match[0])
                return True

        # Fuzzy title + company + location match
        candidates = self.db.execute(
            """
            SELECT canonical_job_id, title, location_city, location_state
            FROM jobs
            WHERE company = ?
              AND posted_date >= date('now', '-90 days')
            LIMIT 200
            """,
            (job.company,),
        ).fetchall()

        loc_a = f"{job.location_city or ''} {job.location_state or ''}".strip()

        for row in candidates:
            loc_b = f"{row['location_city'] or ''} {row['location_state'] or ''}".strip()
            title_sim = fuzz.token_sort_ratio(job.title, row["title"])
            loc_sim = fuzz.ratio(loc_a, loc_b)
            if title_sim >= TITLE_COMPANY_LOC_THRESHOLD and loc_sim >= 80:
                logger.info(
                    "Repost detected via fuzzy match (title=%d%% loc=%d%%): %s → %s",
                    title_sim, loc_sim, job.canonical_job_id, row["canonical_job_id"],
                )
                return True

        return False

    def _enqueue_followup(self, canonical_job_id: str, action_type: str) -> None:
        from datetime import date, timedelta
        due = (date.today() + timedelta(days=1)).isoformat()
        self.db.execute(
            """
            INSERT INTO followup_queue (canonical_job_id, action_type, due_date)
            VALUES (?, ?, ?)
            """,
            (canonical_job_id, action_type, due),
        )
