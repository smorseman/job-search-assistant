"""Google Sheets mirror — SQLite is truth; Sheet is the human-facing view."""

from __future__ import annotations

import logging
import os
import pickle

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

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

# Columns James owns — system writes them only on first insert, then leaves alone
JAMES_OWNED_COLUMNS = {"status", "notes"}
STATUS_COL_IDX = SHEET_HEADERS.index("status")
NOTES_COL_IDX = SHEET_HEADERS.index("notes")
RESUME_COL_IDX = SHEET_HEADERS.index("resume_link")
COVER_COL_IDX = SHEET_HEADERS.index("cover_letter_link")
ID_COL_IDX = SHEET_HEADERS.index("canonical_job_id")


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

    def upsert_row(
        self,
        job_data: dict,
        resume_url: str | None = None,
        cover_url: str | None = None,
    ) -> None:
        """Upsert a job row by canonical_job_id. Idempotent.

        Never overwrites James's `status` or `notes` columns once a row
        exists — those are his to edit; we read them back via sync.
        """
        if not settings.TRACKER_SHEET_ID:
            logger.debug("TRACKER_SHEET_ID not set — skipping Sheet upsert")
            return

        job_id = job_data["canonical_job_id"]
        existing_row_idx = self._find_row(job_id)
        existing_values = self._read_row(existing_row_idx) if existing_row_idx else None

        row = self._build_row(job_data, resume_url, cover_url)

        if existing_values:
            # Preserve James-owned columns (status, notes) and any existing doc links
            # the caller didn't pass — never blow away prior generation links.
            row[STATUS_COL_IDX] = existing_values[STATUS_COL_IDX] or row[STATUS_COL_IDX]
            row[NOTES_COL_IDX] = existing_values[NOTES_COL_IDX] if len(existing_values) > NOTES_COL_IDX else ""
            if not resume_url and len(existing_values) > RESUME_COL_IDX:
                row[RESUME_COL_IDX] = existing_values[RESUME_COL_IDX]
            if not cover_url and len(existing_values) > COVER_COL_IDX:
                row[COVER_COL_IDX] = existing_values[COVER_COL_IDX]

        last_col = self._col_letter(len(SHEET_HEADERS) - 1)
        try:
            if existing_row_idx:
                self._sheets().values().update(
                    spreadsheetId=settings.TRACKER_SHEET_ID,
                    range=f"A{existing_row_idx}:{last_col}{existing_row_idx}",
                    valueInputOption="RAW",
                    body={"values": [row]},
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

    def update_doc_links(self, job_id: str, resume_url: str | None, cover_url: str | None) -> None:
        """Write only the resume_link and cover_letter_link columns for a row."""
        if not settings.TRACKER_SHEET_ID:
            return
        row_idx = self._find_row(job_id)
        if not row_idx:
            logger.warning("update_doc_links: %s not in sheet", job_id)
            return
        resume_col = self._col_letter(RESUME_COL_IDX)
        cover_col = self._col_letter(COVER_COL_IDX)
        try:
            self._sheets().values().batchUpdate(
                spreadsheetId=settings.TRACKER_SHEET_ID,
                body={
                    "valueInputOption": "RAW",
                    "data": [
                        {
                            "range": f"{resume_col}{row_idx}",
                            "values": [[resume_url or ""]],
                        },
                        {
                            "range": f"{cover_col}{row_idx}",
                            "values": [[cover_url or ""]],
                        },
                    ],
                },
            ).execute()
        except HttpError as e:
            logger.error("update_doc_links failed for %s: %s", job_id, e)

    def read_status_column(self) -> list[tuple[str, str]]:
        """Return [(canonical_job_id, status_cell_value), ...] for every data row."""
        if not settings.TRACKER_SHEET_ID:
            return []
        id_col = self._col_letter(ID_COL_IDX)
        status_col = self._col_letter(STATUS_COL_IDX)
        try:
            result = self._sheets().values().batchGet(
                spreadsheetId=settings.TRACKER_SHEET_ID,
                ranges=[f"{id_col}2:{id_col}", f"{status_col}2:{status_col}"],
            ).execute()
            id_values = result["valueRanges"][0].get("values", [])
            status_values = result["valueRanges"][1].get("values", [])
            out: list[tuple[str, str]] = []
            for i, id_row in enumerate(id_values):
                job_id = id_row[0] if id_row else ""
                status = status_values[i][0] if i < len(status_values) and status_values[i] else ""
                if job_id:
                    out.append((job_id, status))
            return out
        except HttpError as e:
            logger.error("read_status_column failed: %s", e)
            return []

    def _read_row(self, row_idx: int) -> list[str] | None:
        last_col = self._col_letter(len(SHEET_HEADERS) - 1)
        try:
            result = self._sheets().values().get(
                spreadsheetId=settings.TRACKER_SHEET_ID,
                range=f"A{row_idx}:{last_col}{row_idx}",
            ).execute()
            values = result.get("values", [])
            return values[0] if values else None
        except HttpError:
            return None

    def _build_row(
        self,
        job_data: dict,
        resume_url: str | None,
        cover_url: str | None,
    ) -> list:
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

        return [
            job_data["canonical_job_id"],
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
            "",
        ]

    @staticmethod
    def _col_letter(idx: int) -> str:
        """0-indexed column number → spreadsheet letter (A, B, ..., Z, AA, ...)."""
        result = ""
        n = idx
        while True:
            result = chr(ord("A") + n % 26) + result
            n = n // 26 - 1
            if n < 0:
                break
        return result

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
