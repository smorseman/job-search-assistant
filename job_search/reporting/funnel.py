"""Funnel statistics — tells James which sources convert and which don't.

This is the loop that improves targeting (per spec §15). Tracks the candidate
journey through state transitions and surfaces conversion rates by source,
discipline, location, and stretch_category.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from sqlite3 import Connection

from job_search.db import get_db

# Funnel stages in order. Each is a milestone in the application journey.
FUNNEL_STAGES = ["discovered", "presented", "selected", "applied", "screen", "interview", "offer"]
TERMINAL_STATES = ("rejected", "ghosted", "offer")


@dataclass
class FunnelStats:
    total_jobs: int = 0
    by_state: dict[str, int] = field(default_factory=dict)
    by_source: dict[str, dict[str, int]] = field(default_factory=dict)
    by_discipline_state: dict[str, dict[str, int]] = field(default_factory=dict)
    by_location_metro: dict[str, dict[str, int]] = field(default_factory=dict)
    by_stretch: dict[str, dict[str, int]] = field(default_factory=dict)
    avg_match_by_state: dict[str, float] = field(default_factory=dict)
    response_rate_by_source: dict[str, dict] = field(default_factory=dict)
    median_days: dict[str, float | None] = field(default_factory=dict)


class FunnelReporter:
    def compute(self) -> FunnelStats:
        stats = FunnelStats()
        with get_db() as db:
            stats.total_jobs = self._total(db)
            stats.by_state = self._by_state(db)
            stats.by_source = self._by_source(db)
            stats.by_stretch = self._by_stretch(db)
            stats.avg_match_by_state = self._avg_match_by_state(db)
            stats.response_rate_by_source = self._response_rate_by_source(db)
            stats.median_days = self._median_days_between_states(db)
        return stats

    # ── Aggregations ──────────────────────────────────────────────────────────

    def _total(self, db: Connection) -> int:
        row = db.execute("SELECT COUNT(*) as n FROM jobs").fetchone()
        return row["n"] if row else 0

    def _by_state(self, db: Connection) -> dict[str, int]:
        rows = db.execute(
            "SELECT app_state, COUNT(*) as n FROM jobs GROUP BY app_state"
        ).fetchall()
        return {r["app_state"]: r["n"] for r in rows}

    def _by_source(self, db: Connection) -> dict[str, dict[str, int]]:
        rows = db.execute("""
            SELECT source, app_state, COUNT(*) as n
            FROM jobs
            GROUP BY source, app_state
            ORDER BY source
        """).fetchall()
        out: dict[str, dict[str, int]] = {}
        for r in rows:
            out.setdefault(r["source"], {})[r["app_state"]] = r["n"]
        return out

    def _by_stretch(self, db: Connection) -> dict[str, dict[str, int]]:
        rows = db.execute("""
            SELECT stretch_category, app_state, COUNT(*) as n
            FROM jobs
            WHERE stretch_category IS NOT NULL
            GROUP BY stretch_category, app_state
        """).fetchall()
        out: dict[str, dict[str, int]] = {}
        for r in rows:
            out.setdefault(r["stretch_category"] or "unknown", {})[r["app_state"]] = r["n"]
        return out

    def _avg_match_by_state(self, db: Connection) -> dict[str, float]:
        rows = db.execute("""
            SELECT app_state, AVG(match_score) as avg_score
            FROM jobs
            WHERE match_score IS NOT NULL
            GROUP BY app_state
        """).fetchall()
        return {r["app_state"]: round(r["avg_score"] or 0, 3) for r in rows}

    def _response_rate_by_source(self, db: Connection) -> dict[str, dict]:
        """For each source: applied count, response count (any progress past applied), response rate."""
        rows = db.execute("""
            SELECT
                source,
                SUM(CASE WHEN app_state IN ('applied','acknowledged','screen','interview','offer','rejected','ghosted') THEN 1 ELSE 0 END) as applied_total,
                SUM(CASE WHEN app_state IN ('acknowledged','screen','interview','offer') THEN 1 ELSE 0 END) as responded,
                SUM(CASE WHEN app_state IN ('screen','interview','offer') THEN 1 ELSE 0 END) as screened,
                SUM(CASE WHEN app_state IN ('interview','offer') THEN 1 ELSE 0 END) as interviewed
            FROM jobs
            GROUP BY source
        """).fetchall()
        out: dict[str, dict] = {}
        for r in rows:
            applied = r["applied_total"] or 0
            if applied == 0:
                continue
            out[r["source"]] = {
                "applied": applied,
                "responded": r["responded"] or 0,
                "response_rate": round((r["responded"] or 0) / applied, 3),
                "screened": r["screened"] or 0,
                "screen_rate": round((r["screened"] or 0) / applied, 3),
                "interviewed": r["interviewed"] or 0,
                "interview_rate": round((r["interviewed"] or 0) / applied, 3),
            }
        return out

    def _median_days_between_states(self, db: Connection) -> dict[str, float | None]:
        """Median days for transitions: applied→acknowledged, applied→screen, applied→rejected/ghosted."""
        return {
            "applied_to_response": self._median_transition_days(
                db, from_state="applied",
                to_states=("acknowledged", "screen", "interview", "offer"),
            ),
            "applied_to_screen": self._median_transition_days(
                db, from_state="applied",
                to_states=("screen",),
            ),
            "applied_to_terminal": self._median_transition_days(
                db, from_state="applied",
                to_states=("rejected", "ghosted"),
            ),
        }

    def _median_transition_days(
        self,
        db: Connection,
        from_state: str,
        to_states: tuple[str, ...],
    ) -> float | None:
        placeholders = ",".join("?" * len(to_states))
        rows = db.execute(f"""
            SELECT
              (julianday(t2.transitioned_at) - julianday(t1.transitioned_at)) as days
            FROM app_transitions t1
            JOIN app_transitions t2
              ON t1.canonical_job_id = t2.canonical_job_id
             AND t1.to_state = ?
             AND t2.to_state IN ({placeholders})
             AND t2.transitioned_at > t1.transitioned_at
        """, (from_state, *to_states)).fetchall()
        values = sorted([r["days"] for r in rows if r["days"] is not None])
        if not values:
            return None
        n = len(values)
        mid = n // 2
        return round((values[mid] if n % 2 else (values[mid - 1] + values[mid]) / 2), 2)
