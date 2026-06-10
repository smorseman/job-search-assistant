"""LLM fit-grading — a cheap pre-triage tier over NEW viable postings.

Runs once per daily pass via the Anthropic **Message Batches API** (−50%):
every new posting that clears the deterministic floor is graded for fit against
James's master profile and gets a categorical grade + one-sentence rationale.
The grade AUGMENTS the deterministic `match_score` (both surface in the Sheet);
it never gates which postings are presented.

This is the only LLM call that runs *before* James flags "apply". The expensive
per-job resume/cover-letter generation (job_search/generation/generator.py)
stays gated on selection.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import anthropic
import yaml

from job_search.config import settings
from job_search.db import get_db

logger = logging.getLogger(__name__)

# Same model as doc-gen; the cost separation comes from the Batches API
# (−50%) plus grade-once persistence, not from the model tier.
MODEL = "claude-sonnet-4-6"

GRADE_RANK = {"Strong": 3, "Good": 2, "Marginal": 1, "Pass": 0}

GRADE_SYSTEM = """You are grading the FIT between a civil-engineering candidate and a SINGLE job posting.
You are NOT writing a resume or cover letter. Output only a categorical grade + one-sentence rationale.

RUBRIC (pick the best category the evidence supports):
- Strong  : Clearly meets core requirements; discipline and seniority align well.
- Good    : Meets most requirements; minor gaps the candidate can credibly cover.
- Marginal: Plausible but with real gaps (discipline mismatch or seniority/experience gap).
- Pass    : Poor fit; a hard requirement the candidate cannot meet (e.g. PE license, years of experience).

RULES (non-negotiable):
1. Cite ONLY facts present in the job description and the candidate profile below. No fabrication.
2. The rationale is ONE sentence naming the deciding factor(s).
3. fit_score is an integer 1-5 (5 = strongest), consistent with the grade bucket.
4. Return ONLY the structured object."""

# json_schema for output_config.format — one object per posting.
GRADE_FORMAT = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["grade", "fit_score", "rationale"],
        "properties": {
            "grade": {"type": "string", "enum": ["Strong", "Good", "Marginal", "Pass"]},
            "fit_score": {"type": "integer", "minimum": 1, "maximum": 5},
            "rationale": {"type": "string", "maxLength": 280},
        },
    },
}


@dataclass
class GradeResult:
    canonical_job_id: str
    grade: str
    fit_score: int | None
    rationale: str
    model_used: str


class FitGrader:
    def __init__(self, client: anthropic.Anthropic | None = None):
        self.client = client or anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        self._profile: dict | None = None
        self._system_cache: str | None = None

    # ── profile (mirrors DocumentGenerator.load_profile) ─────────────────────
    def load_profile(self, path: str | None = None) -> None:
        profile_path = path or settings.PROFILE_PATH
        if not Path(profile_path).exists():
            raise FileNotFoundError(
                f"Profile not found at {profile_path}. "
                f"Copy the template:  cp {settings.PROFILE_TEMPLATE_PATH} {profile_path}  "
                f"and fill in James's real data before running."
            )
        with open(profile_path) as f:
            self._profile = yaml.safe_load(f)
        self._system_cache = None
        logger.info("Profile loaded from %s", profile_path)

    # ── selection ────────────────────────────────────────────────────────────
    def select_viable(self, db, max_jobs: int | None = None) -> list:
        """NEW postings above the floor, not yet graded, skipping deterministically
        dead ones (`long_shot` = hard PE / high-years requirement)."""
        limit = max_jobs or settings.GRADING_MAX_JOBS
        return db.execute(
            """
            SELECT * FROM jobs
            WHERE app_state = 'discovered'
              AND match_score >= ?
              AND llm_graded_at IS NULL
              AND COALESCE(stretch_category, '') != 'long_shot'
            ORDER BY match_score DESC
            LIMIT ?
            """,
            (settings.GRADING_FLOOR, limit),
        ).fetchall()

    # ── request construction ─────────────────────────────────────────────────
    def _system_prompt(self) -> str:
        if self._system_cache is None:
            if not self._profile:
                self.load_profile()
            self._system_cache = (
                GRADE_SYSTEM
                + "\n\nCANDIDATE PROFILE:\n"
                + json.dumps(self._profile, indent=2)
            )
        return self._system_cache

    def _user_message(self, job: dict) -> str:
        jd = job.get("description_normalized") or job.get("description_raw") or ""
        ko: list[str] = []
        if job.get("ko_pe_required"):
            ko.append("PE required")
        if job.get("ko_eit_required"):
            ko.append("EIT required")
        if job.get("ko_min_years"):
            ko.append(f"min {job['ko_min_years']:.0f}yr exp")
        if job.get("ko_degree_required"):
            ko.append(f"degree: {job['ko_degree_required']}")
        return (
            f"ROLE: {job.get('title', '')} @ {job.get('company', '')}\n"
            f"LOCATION: {job.get('location_city', '')}, {job.get('location_state', '')}   "
            f"REMOTE: {job.get('remote_flag', '')}\n"
            f"DETERMINISTIC SIGNALS: match_score={job.get('match_score') or 0:.2f}, "
            f"stretch={job.get('stretch_category', '')}, knockouts={'; '.join(ko) or 'none'}\n\n"
            f"JOB DESCRIPTION:\n{jd[:8000]}\n\n"
            f"Grade the fit."
        )

    def _build_request(self, job: dict) -> dict:
        # custom_id == canonical_job_id (SHA256 → 64 hex chars, matches the
        # ^[A-Za-z0-9_-]{1,64}$ constraint) so result.custom_id IS the job id.
        return {
            "custom_id": job["canonical_job_id"],
            "params": {
                "model": MODEL,
                "max_tokens": 512,
                "system": [
                    {
                        "type": "text",
                        "text": self._system_prompt(),  # byte-identical across requests → cacheable
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                "messages": [{"role": "user", "content": self._user_message(job)}],
                "output_config": {"format": GRADE_FORMAT},
            },
        }

    # ── batch lifecycle ──────────────────────────────────────────────────────
    def submit_batch(self, requests: list[dict]) -> str:
        batch = self.client.messages.batches.create(requests=requests)
        return batch.id

    def poll_until_done(self, batch_id: str, timeout_s: int, interval_s: int | None = None) -> bool:
        interval = interval_s or settings.GRADING_POLL_INTERVAL_S
        deadline = time.monotonic() + timeout_s
        while True:
            batch = self.client.messages.batches.retrieve(batch_id)
            if getattr(batch, "processing_status", None) == "ended":
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(interval)

    def fetch_results(self, batch_id: str) -> list[GradeResult]:
        out: list[GradeResult] = []
        for res in self.client.messages.batches.results(batch_id):
            rtype = getattr(res.result, "type", None)
            if rtype != "succeeded":
                logger.warning("grade result %s: %s (left ungraded for retry)", res.custom_id, rtype)
                continue
            try:
                msg = res.result.message
                text = next(b.text for b in msg.content if getattr(b, "type", None) == "text")
                data = json.loads(text)
                out.append(
                    GradeResult(
                        canonical_job_id=res.custom_id,
                        grade=data["grade"],
                        fit_score=data.get("fit_score"),
                        rationale=data.get("rationale", ""),
                        model_used=getattr(msg, "model", MODEL),
                    )
                )
            except (StopIteration, json.JSONDecodeError, KeyError) as exc:
                logger.warning("grade parse failed for %s: %s", res.custom_id, exc)
        return out

    def persist(self, db, results: list[GradeResult]) -> int:
        n = 0
        for g in results:
            if g.grade not in GRADE_RANK:
                logger.warning("invalid grade %r for %s; skipping", g.grade, g.canonical_job_id)
                continue
            db.execute(
                "UPDATE jobs SET llm_grade=?, llm_fit_score=?, llm_rationale=?, "
                "llm_graded_at=datetime('now'), llm_model=? WHERE canonical_job_id=?",
                (g.grade, g.fit_score, g.rationale, g.model_used, g.canonical_job_id),
            )
            n += 1
        return n

    # ── batch tracking table ─────────────────────────────────────────────────
    def _record_batch(self, db, batch_id: str, job_count: int) -> None:
        db.execute(
            "INSERT OR REPLACE INTO grading_batches (batch_id, status, job_count) "
            "VALUES (?, 'submitted', ?)",
            (batch_id, job_count),
        )

    def _mark_batch(self, db, batch_id: str, status: str) -> None:
        db.execute(
            "UPDATE grading_batches SET status=?, completed_at=datetime('now') WHERE batch_id=?",
            (status, batch_id),
        )

    def drain_prior(self, db) -> int:
        """Finish any prior batch that timed out before its grades were retrieved.
        Persists their grades and marks them drained — so a slow batch is never
        re-graded (never pays twice)."""
        pending = db.execute(
            "SELECT batch_id FROM grading_batches WHERE status = 'submitted'"
        ).fetchall()
        total = 0
        for r in pending:
            bid = r["batch_id"]
            try:
                batch = self.client.messages.batches.retrieve(bid)
            except Exception as exc:  # noqa: BLE001 — best-effort drain
                logger.warning("drain_prior: retrieve %s failed: %s", bid, exc)
                continue
            if getattr(batch, "processing_status", None) != "ended":
                continue  # still running — try again next run
            results = self.fetch_results(bid)
            total += self.persist(db, results)
            self._mark_batch(db, bid, "drained")
        return total

    # ── orchestration ────────────────────────────────────────────────────────
    def run(
        self,
        timeout_s: int | None = None,
        max_jobs: int | None = None,
        dry_run: bool = False,
    ) -> dict:
        stats = {
            "enabled": settings.GRADING_ENABLED,
            "drained": 0,
            "selected": 0,
            "graded": 0,
            "timed_out": False,
            "batch_id": None,
        }
        if not settings.GRADING_ENABLED:
            return stats

        timeout_s = timeout_s if timeout_s is not None else settings.GRADING_POLL_TIMEOUT_S
        limit = max_jobs or settings.GRADING_MAX_JOBS

        # Phase A — drain any prior batch, then select what's new and viable.
        with get_db() as db:
            stats["drained"] = self.drain_prior(db)
            rows = [dict(r) for r in self.select_viable(db, limit)]
        stats["selected"] = len(rows)
        if not rows:
            return stats

        requests = [self._build_request(r) for r in rows]
        if dry_run:
            stats["dry_run"] = True
            return stats

        # Phase B — submit and poll (no DB held open during the wait).
        batch_id = self.submit_batch(requests)
        stats["batch_id"] = batch_id
        with get_db() as db:
            self._record_batch(db, batch_id, len(rows))

        if not self.poll_until_done(batch_id, timeout_s):
            stats["timed_out"] = True  # leave 'submitted' → drained next run
            logger.warning("grading batch %s not done in %ss; report falls back to deterministic score", batch_id, timeout_s)
            return stats

        # Phase C — retrieve, persist, mark drained.
        results = self.fetch_results(batch_id)
        with get_db() as db:
            stats["graded"] = self.persist(db, results)
            self._mark_batch(db, batch_id, "drained")
        return stats
