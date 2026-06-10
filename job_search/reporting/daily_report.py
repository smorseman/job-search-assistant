"""Daily review report — presents top-scored postings WITHOUT generating docs.

Doc generation is deferred until James selects which jobs he actually wants
to apply to (see SelectionProcessor). This keeps LLM calls aligned with
applications submitted, not jobs surfaced.
"""

from __future__ import annotations

import logging
import tempfile
from datetime import date
from pathlib import Path

from job_search.config import settings
from job_search.db import get_db

from .sheets import SheetsLogger

logger = logging.getLogger(__name__)

# Jobs above this score get surfaced in the daily report
PRESENTATION_THRESHOLD = 0.55
MAX_PRESENTATIONS_PER_RUN = 30


class DailyReporter:
    """Surfaces top-scored postings to the Sheet and a Drive report.

    Does NOT generate resumes/cover letters — that happens only after James
    flags a job as 'apply' in the Sheet (or via `jsa generate <job_id>`).
    """

    def __init__(self):
        self.sheets = SheetsLogger()

    def run(self) -> dict:
        today = date.today().isoformat()
        try:
            self.sheets.ensure_headers()
        except Exception as exc:
            logger.warning("Sheets ensure_headers failed: %s", exc)

        stats = {"date": today, "presented": 0, "errors": 0}
        report_lines = [f"# Job Search Daily Report — {today}\n", "", "_Set status to 'apply' in the Sheet for any job you want resume + cover letter generated._\n"]

        with get_db() as db:
            candidates = db.execute(
                """
                SELECT * FROM jobs
                WHERE app_state = 'discovered'
                  AND match_score >= ?
                ORDER BY match_score DESC
                LIMIT ?
                """,
                (PRESENTATION_THRESHOLD, MAX_PRESENTATIONS_PER_RUN),
            ).fetchall()

            logger.info("Daily report: %d candidates above threshold", len(candidates))

            for row in candidates:
                job_dict = dict(row)
                job_id = job_dict["canonical_job_id"]
                try:
                    # Advance state: discovered → presented
                    db.execute(
                        "UPDATE jobs SET app_state = 'presented', updated_at = datetime('now') "
                        "WHERE canonical_job_id = ?",
                        (job_id,),
                    )
                    db.execute(
                        "INSERT INTO app_transitions (canonical_job_id, from_state, to_state, note) "
                        "VALUES (?, 'discovered', 'presented', 'daily_report')",
                        (job_id,),
                    )
                    job_dict["app_state"] = "presented"

                    # Mirror to Sheet (NO doc generation — defer until selected)
                    try:
                        self.sheets.upsert_row(job_dict)
                    except Exception as exc:
                        logger.warning("Sheet upsert failed for %s: %s", job_id, exc)

                    stats["presented"] += 1
                    report_lines.append(self._format_report_line(job_dict))

                except Exception as exc:
                    logger.error("Failed to present %s: %s", job_id, exc)
                    stats["errors"] += 1

            report_text = "\n".join(report_lines)
            self._upload_report(report_text, today, db)

        return stats

    def _format_report_line(self, job_dict: dict) -> str:
        ko_parts = self._format_knockouts(job_dict)
        stretch = job_dict.get("stretch_category", "")
        return (
            f"## {job_dict['title']} @ {job_dict['company']}\n"
            f"- **Score:** {job_dict.get('match_score', 0):.1%}  "
            f"**Stretch:** {stretch}  "
            f"**Benefit:** {job_dict.get('benefit_score', 0):.1%}  "
            f"**Trajectory:** {job_dict.get('career_trajectory_score', 0):.1%}\n"
            f"- **Location:** {job_dict.get('location_city', '')}, {job_dict.get('location_state', '')}\n"
            f"- **Apply:** {job_dict.get('apply_url', 'N/A')}\n"
            f"- **Knockouts:** {ko_parts or 'none detected'}\n"
            f"- **Job ID:** `{job_dict['canonical_job_id']}`\n"
        )

    def _format_knockouts(self, job_dict: dict) -> str:
        parts = []
        if job_dict.get("ko_pe_required"):
            parts.append("⚠ PE required")
        if job_dict.get("ko_eit_required"):
            parts.append("EIT required")
        if job_dict.get("ko_min_years"):
            parts.append(f"Min {job_dict['ko_min_years']:.0f} yrs exp")
        if job_dict.get("ko_degree_required"):
            parts.append(f"Degree: {job_dict['ko_degree_required']}")
        return "; ".join(parts)

    def _upload_report(self, text: str, report_date: str, db) -> None:
        if not settings.DRIVE_ROOT_FOLDER_ID:
            return
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(text)
            tmp = f.name
        try:
            url = self.sheets.upload_document(tmp, f"daily_report_{report_date}.md")
            db.execute(
                "INSERT INTO daily_reports (report_date, drive_file_id) VALUES (?, ?)",
                (report_date, url),
            )
            logger.info("Daily report uploaded: %s", url)
        except Exception as exc:
            logger.warning("Report upload failed: %s", exc)
        finally:
            Path(tmp).unlink(missing_ok=True)
