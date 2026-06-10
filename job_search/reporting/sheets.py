"""Google Sheets mirror — SQLite is truth; Sheet is the human-facing view."""

from __future__ import annotations

import logging
from typing import Any

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import pickle
import os

from job_search.config import settings

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
    "https://mail.google.com/",
]

SHEET_HEADERS = [
    "canonical_job_id", "company", "title", "source", "discipline",
    "applied_date", "status", "next_action_date",
    "match_score", "keyword_coverage", "stretch_category",
    "location", "salary_range", "remote",
    "jd_link", "resume_link", "cover_letter_link",
    "knockout_flags", "benefit_score", "trajectory_score",
    "notes",
]


class SheetsLogger:
    def __init__(self):
        self._service = None
        self._drive = None

    def _get_creds(self) -> Credentials:
        creds = None
        token_path = settings.GOOGLE_TOKEN_PATH

        if os.path.exists(token_path):
            with open(token_path, "rb") as f:
                creds = pickle.load(f)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    settings.GOOGLE_CREDENTIALS_PATH, SCOPES
                )
                creds = flow.run_local_server(port=0)
            with open(token_path, "wb") as f:
                pickle.dump(creds, f)

        return creds

    def _sheets(self):
        if not self._service:
            creds = self._get_creds()
            self._service = build("sheets", "v4", credentials=creds)
        return self._service.spreadsheets()

    def _drive_service(self):
        if not self._drive:
            creds = self._get_creds()
            self._drive = build("drive", "v3", credentials=creds)
        return self._drive

    def ensure_headers(self) -> None:
        """Create the header row if the sheet is empty."""
        try:
            result = self._sheets().values().get(
                spreadsheetId=settings.TRACKER_SHEET_ID,
                range="A1:Z1",
            ).execute()
            if not result.get("values"):
                self._sheets().values().update(
                    spreadsheetId=settings.TRACKER_SHEET_ID,
                    range="A1",
                    valueInputOption="RAW",
                    body={"values": [SHEET_HEADERS]},
                ).execute()
                logger.info("Sheet headers written")
        except HttpError as e:
            logger.error("Sheets API error: %s", e)

    def upsert_row(self, job_data: dict, resume_url: str | None = None, cover_url: str | None = None) -> None:
        """Upsert a job row by canonical_job_id. Idempotent."""
        if not settings.TRACKER_SHEET_ID:
            logger.debug("TRACKER_SHEET_ID not set — skipping Sheet upsert")
            return

        job_id = job_data["canonical_job_id"]
        existing_row = self._find_row(job_id)

        location = f"{job_data.get('location_city', '')}, {job_data.get('location_state', '')}".strip(", ")
        sal_min = job_data.get("salary_min")
        sal_max = job_data.get("salary_max")
        salary_range = f"${sal_min:,}–${sal_max:,}" if sal_min and sal_max else ""

        ko_parts = []
        if job_data.get("ko_pe_required"):
            ko_parts.append("PE required")
        if job_data.get("ko_eit_required"):
            ko_parts.append("EIT required")
        if job_data.get("ko_min_years"):
            ko_parts.append(f"Min {job_data['ko_min_years']:.0f}yr")
        if job_data.get("ko_degree_required"):
            ko_parts.append(f"Degree: {job_data['ko_degree_required']}")

        row = [
            job_id,
            job_data.get("company", ""),
            job_data.get("title", ""),
            job_data.get("source", ""),
            ",".join((job_data.get("discipline_tags") or [])[:2]),
            job_data.get("applied_date", ""),
            job_data.get("app_state", "discovered"),
            job_data.get("next_action_date", ""),
            round(job_data.get("match_score") or 0, 3),
            round(job_data.get("keyword_coverage") or 0, 3),
            job_data.get("stretch_category", ""),
            location,
            salary_range,
            job_data.get("remote_flag", ""),
            job_data.get("apply_url", ""),
            resume_url or "",
            cover_url or "",
            "; ".join(ko_parts),
            round(job_data.get("benefit_score") or 0, 3),
            round(job_data.get("career_trajectory_score") or 0, 3),
            "",  # notes — James fills this
        ]

        try:
            if existing_row:
                # Update in place, but preserve James's notes column (last col)
                range_addr = f"A{existing_row}:{chr(ord('A') + len(SHEET_HEADERS) - 2)}{existing_row}"
                self._sheets().values().update(
                    spreadsheetId=settings.TRACKER_SHEET_ID,
                    range=range_addr,
                    valueInputOption="RAW",
                    body={"values": [row[:-1]]},  # preserve notes
                ).execute()
            else:
                self._sheets().values().append(
                    spreadsheetId=settings.TRACKER_SHEET_ID,
                    range="A1",
                    valueInputOption="RAW",
                    insertDataOption="INSERT_ROWS",
                    body={"values": [row]},
                ).execute()
        except HttpError as e:
            logger.error("Sheets upsert error for %s: %s", job_id, e)

    def _find_row(self, canonical_job_id: str) -> int | None:
        """Return 1-based row number if job_id exists, else None."""
        try:
            result = self._sheets().values().get(
                spreadsheetId=settings.TRACKER_SHEET_ID,
                range="A:A",
            ).execute()
            values = result.get("values", [])
            for i, row in enumerate(values):
                if row and row[0] == canonical_job_id:
                    return i + 1
        except HttpError:
            pass
        return None

    def upload_document(self, local_path: str, filename: str, folder_id: str | None = None) -> str | None:
        """Upload a file to Drive, return its web URL."""
        from googleapiclient.http import MediaFileUpload
        folder = folder_id or settings.DRIVE_ROOT_FOLDER_ID
        if not folder:
            return None
        try:
            meta = {"name": filename, "parents": [folder]}
            media = MediaFileUpload(local_path, resumable=False)
            file = self._drive_service().files().create(
                body=meta, media_body=media, fields="id,webViewLink"
            ).execute()
            return file.get("webViewLink")
        except HttpError as e:
            logger.error("Drive upload error: %s", e)
            return None
