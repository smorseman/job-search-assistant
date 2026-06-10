"""Tests for SelectionProcessor sync logic (no live Sheet calls)."""

import sqlite3
from unittest.mock import MagicMock

import pytest

from job_search.db.connection import init_db
from job_search.models import CanonicalJob
from job_search.reporting.selection import SelectionProcessor
from job_search.reporting.sheets import SheetsLogger
from job_search.tracking import advance_state


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr("job_search.config.settings.DB_PATH", db_path)
    monkeypatch.setattr("job_search.config.settings.TRACKER_SHEET_ID", "test-sheet-id")
    init_db(db_path)
    yield db_path


def _insert_job(db_path: str, job_id: str = "job1", state: str = "presented"):
    """Insert a minimal job row at the given state."""
    from job_search.ingestion.dedup import Deduplicator
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    dedup = Deduplicator(conn)
    dedup.upsert(CanonicalJob(
        canonical_job_id=job_id,
        source="test",
        source_job_id=job_id,
        company="Acme Engineering",
        title="Civil Engineer",
        description_normalized="structural design",
    ))
    if state != "discovered":
        # Walk it forward to the target state
        if state in ("presented", "selected", "applied", "rejected"):
            advance_state(conn, job_id, "presented", note="test setup")
        if state in ("selected", "applied"):
            advance_state(conn, job_id, "selected", note="test setup")
        if state == "applied":
            advance_state(conn, job_id, "applied", note="test setup")
        if state == "rejected":
            # rejected from presented; nothing else needed
            pass
    conn.commit()
    conn.close()


def _check_state(db_path: str, job_id: str) -> str:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT app_state FROM jobs WHERE canonical_job_id = ?", (job_id,)).fetchone()
    conn.close()
    return row["app_state"] if row else ""


def test_apply_status_moves_job_to_selected(db, monkeypatch):
    _insert_job(db, "job1", "presented")

    # Mock the sheet read to return one row with status="apply"
    mock_sheets = MagicMock(spec=SheetsLogger)
    mock_sheets.read_status_column.return_value = [("job1", "apply")]

    proc = SelectionProcessor()
    proc.sheets = mock_sheets
    stats = proc.sync_from_sheet()

    assert stats["selected"] == 1
    assert _check_state(db, "job1") == "selected"


def test_applied_status_advances_through_selected(db, monkeypatch):
    _insert_job(db, "job1", "selected")

    mock_sheets = MagicMock(spec=SheetsLogger)
    mock_sheets.read_status_column.return_value = [("job1", "applied")]

    proc = SelectionProcessor()
    proc.sheets = mock_sheets
    stats = proc.sync_from_sheet()

    assert stats["applied"] == 1
    assert _check_state(db, "job1") == "applied"


def test_skip_status_moves_to_rejected(db):
    _insert_job(db, "job1", "presented")

    mock_sheets = MagicMock(spec=SheetsLogger)
    mock_sheets.read_status_column.return_value = [("job1", "skip")]

    proc = SelectionProcessor()
    proc.sheets = mock_sheets
    stats = proc.sync_from_sheet()

    assert stats["rejected"] == 1
    assert _check_state(db, "job1") == "rejected"


def test_unrecognized_status_is_ignored(db):
    _insert_job(db, "job1", "presented")

    mock_sheets = MagicMock(spec=SheetsLogger)
    mock_sheets.read_status_column.return_value = [("job1", "thinking about it")]

    proc = SelectionProcessor()
    proc.sheets = mock_sheets
    stats = proc.sync_from_sheet()

    assert stats["synced"] == 0
    assert _check_state(db, "job1") == "presented"


def test_already_in_target_state_no_advance(db):
    _insert_job(db, "job1", "selected")

    mock_sheets = MagicMock(spec=SheetsLogger)
    mock_sheets.read_status_column.return_value = [("job1", "apply")]   # already selected

    proc = SelectionProcessor()
    proc.sheets = mock_sheets
    stats = proc.sync_from_sheet()

    assert stats["selected"] == 0    # no change


# ── _col_letter helper ───────────────────────────────────────────────────────

def test_col_letter_basic():
    assert SheetsLogger._col_letter(0) == "A"
    assert SheetsLogger._col_letter(20) == "U"
    assert SheetsLogger._col_letter(25) == "Z"
    assert SheetsLogger._col_letter(26) == "AA"
    assert SheetsLogger._col_letter(27) == "AB"
