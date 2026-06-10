"""Tests for deduplication and repost detection."""

import sqlite3
import pytest

from job_search.db.connection import init_db
from job_search.ingestion.dedup import Deduplicator
from job_search.models import CanonicalJob


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    yield conn
    conn.close()


def make_job(**kwargs) -> CanonicalJob:
    defaults = dict(
        source="greenhouse",
        source_job_id="job_001",
        company="Acme Engineering",
        title="Civil Engineer",
        location_city="Austin",
        location_state="TX",
        description_normalized="structural design AutoCAD Civil 3D bridge",
    )
    defaults.update(kwargs)
    return CanonicalJob(**defaults)


def test_first_insert_is_new(db):
    dedup = Deduplicator(db)
    job = make_job()
    is_new, is_repost = dedup.upsert(job)
    assert is_new is True
    assert is_repost is False


def test_second_insert_same_id_is_not_new(db):
    dedup = Deduplicator(db)
    job = make_job()
    dedup.upsert(job)
    is_new, is_repost = dedup.upsert(job)
    assert is_new is False


def test_fuzzy_repost_detected(db):
    dedup = Deduplicator(db)
    # Insert original
    job1 = make_job(source_job_id="job_001", title="Civil Engineer I")
    dedup.upsert(job1)

    # Same company, same location, very similar title → should detect as repost
    job2 = make_job(source_job_id="job_002", title="Civil Engineer I - Updated Posting")
    is_new, is_repost = dedup.upsert(job2)
    assert is_new is True
    assert is_repost is True


def test_different_company_no_repost(db):
    dedup = Deduplicator(db)
    job1 = make_job(source_job_id="job_001", company="Firm A")
    dedup.upsert(job1)

    job2 = make_job(source_job_id="job_002", company="Firm B")
    is_new, is_repost = dedup.upsert(job2)
    assert is_new is True
    assert is_repost is False
