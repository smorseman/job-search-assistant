"""Tests for FunnelReporter — shapes + correctness on synthetic data."""

import sqlite3

import pytest

from job_search.db.connection import init_db
from job_search.ingestion.dedup import Deduplicator
from job_search.models import CanonicalJob
from job_search.reporting.funnel import FunnelReporter
from job_search.tracking import advance_state


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr("job_search.config.settings.DB_PATH", db_path)
    init_db(db_path)
    yield db_path


def _seed(db_path, source: str, job_id: str, final_state: str, match_score: float = 0.7):
    """Insert a job and walk it forward through valid transitions."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    dedup = Deduplicator(conn)
    dedup.upsert(CanonicalJob(
        canonical_job_id=job_id,
        source=source,
        source_job_id=job_id,
        company=f"Firm {job_id}",
        title="Civil Engineer",
        match_score=match_score,
        stretch_category="qualified",
    ))

    # Walk forward
    path = {
        "discovered": [],
        "presented": ["presented"],
        "selected":  ["presented", "selected"],
        "applied":   ["presented", "selected", "applied"],
        "screen":    ["presented", "selected", "applied", "screen"],
        "interview": ["presented", "selected", "applied", "screen", "interview"],
        "offer":     ["presented", "selected", "applied", "screen", "interview", "offer"],
        "rejected":  ["presented", "selected", "applied", "rejected"],
        "ghosted":   ["presented", "selected", "applied", "ghosted"],
    }[final_state]
    for state in path:
        advance_state(conn, job_id, state, note="test seed")
    conn.commit()
    conn.close()


def test_funnel_basic_counts(db):
    _seed(db, "greenhouse", "j1", "presented")
    _seed(db, "greenhouse", "j2", "applied")
    _seed(db, "usajobs",    "j3", "presented")
    _seed(db, "usajobs",    "j4", "interview")
    _seed(db, "usajobs",    "j5", "rejected")

    stats = FunnelReporter().compute()
    assert stats.total_jobs == 5
    assert stats.by_state["presented"] == 2
    assert stats.by_state["applied"] == 1
    assert stats.by_state["interview"] == 1
    assert stats.by_state["rejected"] == 1


def test_funnel_by_source(db):
    _seed(db, "greenhouse", "j1", "applied")
    _seed(db, "greenhouse", "j2", "rejected")
    _seed(db, "lever",      "j3", "interview")
    _seed(db, "usajobs",    "j4", "presented")

    stats = FunnelReporter().compute()
    assert "greenhouse" in stats.by_source
    assert stats.by_source["greenhouse"]["applied"] == 1
    assert stats.by_source["greenhouse"]["rejected"] == 1
    assert stats.by_source["lever"]["interview"] == 1
    assert stats.by_source["usajobs"]["presented"] == 1


def test_response_rate_by_source(db):
    # USAJOBS: 3 applied, 2 got a response (1 screen + 1 rejected)
    # Actually rejected is NOT a response in our model
    _seed(db, "usajobs", "j1", "interview")    # responded
    _seed(db, "usajobs", "j2", "rejected")     # applied but rejected (no response)
    _seed(db, "usajobs", "j3", "ghosted")      # applied, no response
    _seed(db, "usajobs", "j4", "screen")       # responded

    stats = FunnelReporter().compute()
    usa = stats.response_rate_by_source["usajobs"]
    assert usa["applied"] == 4
    assert usa["responded"] == 2     # interview + screen count as responses
    assert abs(usa["response_rate"] - 0.5) < 0.001


def test_avg_match_by_state(db):
    _seed(db, "greenhouse", "j1", "applied",   match_score=0.85)
    _seed(db, "greenhouse", "j2", "applied",   match_score=0.65)
    _seed(db, "greenhouse", "j3", "rejected",  match_score=0.55)

    stats = FunnelReporter().compute()
    assert abs(stats.avg_match_by_state["applied"] - 0.75) < 0.001
    assert abs(stats.avg_match_by_state["rejected"] - 0.55) < 0.001


def test_empty_db_returns_zeros(db):
    stats = FunnelReporter().compute()
    assert stats.total_jobs == 0
    assert stats.by_state == {}
    assert stats.by_source == {}
    assert stats.response_rate_by_source == {}
