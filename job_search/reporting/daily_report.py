"""Daily review report — pairs JD summary, tailored docs, apply link, and flags."""

from __future__ import annotations

import logging
import tempfile
from datetime import date
from pathlib import Path

from job_search.config import settings
from job_search.db import get_db
from job_search.generation import DocumentGenerator
from job_search.models import AppState

from .sheets import SheetsLogger

logger = logging.getLogger(__name__)

# Jobs above this score get full document generation
GENERATION_THRESHOLD = 0.55
# Cap per-day generated docs to control API cost
MAX_DOCS_PER_RUN = 15


class DailyReporter:
    def __init__(self):
        self.generator = DocumentGenerator()
        self.sheets = SheetsLogger()

    def run(self) -> dict:
        today = date.today().isoformat()
        self.generator.load_profile()
        self.sheets.ensure_headers()

        stats = {"date": today, "presented": 0, "docs_generated": 0, "errors": 0}

        with get_db() as db:
            candidates = db.execute(
                """
                SELECT * FROM jobs
                WHERE app_state = 'discovered'
                  AND match_score >= ?
                ORDER BY match_score DESC
                LIMIT 50
                """,
                (GENERATION_THRESHOLD,),
            ).fetchall()

            logger.info("Daily report: %d candidates above threshold", len(candidates))

            report_lines = [f"# Job Search Daily Report — {today}\n"]
            doc_count = 0

            for row in candidates:
                job_dict = dict(row)
                job_id = job_dict["canonical_job_id"]

                try:
                    resume_url, cover_url = None, None

                    if doc_count < MAX_DOCS_PER_RUN and not settings.DRY_RUN:
                        # Re-hydrate a minimal CanonicalJob for generation
                        from job_search.models import CanonicalJob, ATSType, KnockoutFields
                        import json
                        job_obj = CanonicalJob(
                            source=job_dict["source"],
                            source_job_id=job_dict["source_job_id"],
                            firm_id=job_dict.get("firm_id"),
                            company=job_dict["company"],
                            title=job_dict["title"],
                            location_city=job_dict.get("location_city"),
                            location_state=job_dict.get("location_state"),
                            description_normalized=job_dict.get("description_normalized"),
                            description_raw=job_dict.get("description_raw"),
                            apply_url=job_dict.get("apply_url"),
                            ats_type=ATSType(job_dict.get("ats_type", "unknown")),
                        )
                        result = self.generator.generate(job_obj)
                        doc_count += 1

                        # Save + upload to Drive
                        with tempfile.TemporaryDirectory() as tmpdir:
                            safe_company = "".join(c for c in job_dict["company"] if c.isalnum() or c in " -_")[:30]
                            safe_title = "".join(c for c in job_dict["title"] if c.isalnum() or c in " -_")[:30]
                            prefix = f"{today}_{safe_company}_{safe_title}".replace(" ", "_")

                            resume_path = str(Path(tmpdir) / f"{prefix}_resume.docx")
                            cover_path = str(Path(tmpdir) / f"{prefix}_cover.txt")

                            self.generator.save_docx(result["resume_json"], resume_path)
                            Path(cover_path).write_text(result["cover_letter_text"])

                            # Create per-application Drive folder
                            folder_id = self._get_or_create_drive_folder(prefix)
                            resume_url = self.sheets.upload_document(resume_path, f"{prefix}_resume.docx", folder_id)
                            cover_url = self.sheets.upload_document(cover_path, f"{prefix}_cover.txt", folder_id)

                        # Log to generated_docs
                        db.execute(
                            """
                            INSERT INTO generated_docs
                              (canonical_job_id, doc_type, drive_url, keyword_coverage, keywords_hit, keywords_missed, model_used)
                            VALUES (?, 'resume', ?, ?, ?, ?, ?)
                            """,
                            (
                                job_id,
                                resume_url,
                                result["keyword_coverage"],
                                str(result["keywords_hit"]),
                                str(result["keywords_missed"]),
                                "claude-sonnet-4-6",
                            ),
                        )

                    # Advance state: discovered → presented
                    db.execute(
                        "UPDATE jobs SET app_state = 'presented', updated_at = datetime('now') WHERE canonical_job_id = ?",
                        (job_id,),
                    )
                    db.execute(
                        "INSERT INTO app_transitions (canonical_job_id, from_state, to_state, note) VALUES (?, 'discovered', 'presented', 'daily_report')",
                        (job_id,),
                    )

                    # Mirror to Sheets
                    self.sheets.upsert_row(job_dict, resume_url, cover_url)

                    stats["presented"] += 1
                    stats["docs_generated"] += 1 if resume_url else 0

                    # Add to report
                    ko_flags = self._format_knockouts(job_dict)
                    stretch = job_dict.get("stretch_category", "")
                    report_lines.append(
                        f"## {job_dict['title']} @ {job_dict['company']}\n"
                        f"- **Score:** {job_dict.get('match_score', 0):.1%}  "
                        f"**Stretch:** {stretch}  "
                        f"**Benefit:** {job_dict.get('benefit_score', 0):.1%}  "
                        f"**Trajectory:** {job_dict.get('career_trajectory_score', 0):.1%}\n"
                        f"- **Location:** {job_dict.get('location_city', '')}, {job_dict.get('location_state', '')}\n"
                        f"- **Apply:** {job_dict.get('apply_url', 'N/A')}\n"
                        f"- **Resume:** {resume_url or 'not generated'}\n"
                        f"- **Cover letter:** {cover_url or 'not generated'}\n"
                        f"- **Knockouts:** {ko_flags or 'none detected'}\n"
                    )

                except Exception as exc:
                    logger.error("Failed to process %s: %s", job_id, exc)
                    stats["errors"] += 1

            # Save report to Drive
            report_text = "\n".join(report_lines)
            self._upload_report(report_text, today, db)

        return stats

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

    def _get_or_create_drive_folder(self, name: str) -> str | None:
        if not settings.DRIVE_ROOT_FOLDER_ID:
            return None
        try:
            drive = self.sheets._drive_service()
            meta = {
                "name": name,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [settings.DRIVE_ROOT_FOLDER_ID],
            }
            folder = drive.files().create(body=meta, fields="id").execute()
            return folder.get("id")
        except Exception as exc:
            logger.error("Could not create Drive folder: %s", exc)
            return settings.DRIVE_ROOT_FOLDER_ID

    def _upload_report(self, text: str, report_date: str, db) -> None:
        import tempfile
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
        finally:
            Path(tmp).unlink(missing_ok=True)
