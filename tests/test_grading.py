"""Tests for the LLM fit-grading tier (no network — batch client is mocked)."""

import json
import re
import sqlite3
from types import SimpleNamespace

import pytest

from job_search.db.connection import init_db
from job_search.grading import FitGrader, GradeResult

VALID_ID = "a" * 64  # 64 hex chars, like a real canonical_job_id (SHA256)


# ── fake Anthropic batch client ──────────────────────────────────────────────
def _text_block(text):
    return SimpleNamespace(type="text", text=text)


def _succeeded(custom_id, payload, model="claude-sonnet-4-6"):
    msg = SimpleNamespace(content=[_text_block(json.dumps(payload))], model=model)
    return SimpleNamespace(
        custom_id=custom_id,
        result=SimpleNamespace(type="succeeded", message=msg),
    )


def _errored(custom_id):
    return SimpleNamespace(custom_id=custom_id, result=SimpleNamespace(type="errored"))


class FakeBatches:
    def __init__(self, *, status="ended", results=None, batch_id="batch_test"):
        self._status = status
        self._results = results or []
        self._batch_id = batch_id
        self.created: list = []

    def create(self, requests):
        self.created.append(requests)
        return SimpleNamespace(id=self._batch_id)

    def retrieve(self, batch_id):
        return SimpleNamespace(processing_status=self._status)

    def results(self, batch_id):
        return list(self._results)


def _client(batches):
    return SimpleNamespace(messages=SimpleNamespace(batches=batches))


def _grader(batches, profile=None):
    g = FitGrader(client=_client(batches))
    g._profile = profile or {"identity": {"first_name": "James", "last_name": "Morseman"}}
    return g


# ── DB helpers ───────────────────────────────────────────────────────────────
@pytest.fixture
def db_path(tmp_path, monkeypatch):
    p = str(tmp_path / "test.db")
    monkeypatch.setattr("job_search.config.settings.DB_PATH", p)
    init_db(p)
    return p


def _conn(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _insert(conn, job_id, match_score=0.7, state="discovered",
            stretch="qualified", graded_at=None):
    conn.execute(
        "INSERT INTO jobs (canonical_job_id, source, source_job_id, company, title, "
        "description_normalized, match_score, stretch_category, app_state, llm_graded_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (job_id, "test", job_id, "Acme Eng", "Civil Engineer",
         "structural design of bridges", match_score, stretch, state, graded_at),
    )
    conn.commit()


# ── selection ────────────────────────────────────────────────────────────────
def test_select_viable_filters_and_orders(db_path):
    conn = _conn(db_path)
    _insert(conn, "hi", match_score=0.90)                       # in
    _insert(conn, "lo", match_score=0.40)                       # out: below floor
    _insert(conn, "mid", match_score=0.70)                      # in
    _insert(conn, "shot", match_score=0.95, stretch="long_shot")  # out: long_shot
    _insert(conn, "seen", match_score=0.95, graded_at="2026-01-01")  # out: already graded
    _insert(conn, "pres", match_score=0.95, state="presented")  # out: not discovered

    rows = _grader(FakeBatches()).select_viable(conn, max_jobs=10)
    ids = [r["canonical_job_id"] for r in rows]
    assert ids == ["hi", "mid"]  # ordered by match_score DESC


def test_select_viable_respects_cap(db_path):
    conn = _conn(db_path)
    for i in range(5):
        _insert(conn, f"j{i}", match_score=0.6 + i / 100)
    rows = _grader(FakeBatches()).select_viable(conn, max_jobs=3)
    assert len(rows) == 3


# ── request construction ─────────────────────────────────────────────────────
def test_custom_id_is_canonical_job_id():
    job = {"canonical_job_id": VALID_ID, "title": "CE", "company": "Acme",
           "description_normalized": "bridges"}
    req = _grader(FakeBatches())._build_request(job)
    assert req["custom_id"] == VALID_ID
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,64}", req["custom_id"])


def test_request_carries_schema_and_cached_profile():
    job = {"canonical_job_id": VALID_ID, "title": "CE", "company": "Acme",
           "description_normalized": "bridges"}
    req = _grader(FakeBatches())._build_request(job)
    params = req["params"]

    schema = params["output_config"]["format"]["schema"]
    assert schema["properties"]["grade"]["enum"] == ["Strong", "Good", "Marginal", "Pass"]
    assert schema["properties"]["fit_score"]["maximum"] == 5

    sys_block = params["system"][0]
    assert sys_block["cache_control"] == {"type": "ephemeral"}
    assert "James" in sys_block["text"]          # profile embedded
    assert params["model"] == "claude-sonnet-4-6"


# ── results + persistence ────────────────────────────────────────────────────
def test_fetch_results_keeps_only_succeeded():
    batches = FakeBatches(results=[
        _succeeded("good", {"grade": "Strong", "fit_score": 5, "rationale": "fits"}),
        _errored("bad"),
    ])
    results = _grader(batches).fetch_results("b")
    assert len(results) == 1
    assert results[0].canonical_job_id == "good"
    assert results[0].grade == "Strong"


def test_persist_sets_columns_and_grade_once(db_path):
    conn = _conn(db_path)
    _insert(conn, "j1", match_score=0.8)
    grader = _grader(FakeBatches())

    n = grader.persist(conn, [GradeResult("j1", "Good", 4, "solid match", "claude-sonnet-4-6")])
    conn.commit()
    assert n == 1

    row = conn.execute(
        "SELECT llm_grade, llm_fit_score, llm_rationale, llm_graded_at FROM jobs WHERE canonical_job_id='j1'"
    ).fetchone()
    assert row["llm_grade"] == "Good"
    assert row["llm_fit_score"] == 4
    assert row["llm_graded_at"] is not None

    # grade-once: a graded job is no longer selected
    assert _grader(FakeBatches()).select_viable(conn) == []


def test_persist_rejects_invalid_grade(db_path):
    conn = _conn(db_path)
    _insert(conn, "j1", match_score=0.8)
    n = _grader(FakeBatches()).persist(conn, [GradeResult("j1", "Excellent", 9, "x", "m")])
    conn.commit()
    assert n == 0
    row = conn.execute("SELECT llm_grade FROM jobs WHERE canonical_job_id='j1'").fetchone()
    assert row["llm_grade"] is None


# ── drain prior batch ────────────────────────────────────────────────────────
def test_drain_prior_finishes_open_batch(db_path):
    conn = _conn(db_path)
    _insert(conn, "j1", match_score=0.8)
    conn.execute(
        "INSERT INTO grading_batches (batch_id, status, job_count) VALUES ('bprev', 'submitted', 1)"
    )
    conn.commit()

    batches = FakeBatches(status="ended", results=[
        _succeeded("j1", {"grade": "Marginal", "fit_score": 2, "rationale": "gap"}),
    ])
    drained = _grader(batches).drain_prior(conn)
    conn.commit()

    assert drained == 1
    assert conn.execute("SELECT llm_grade FROM jobs WHERE canonical_job_id='j1'").fetchone()[0] == "Marginal"
    assert conn.execute("SELECT status FROM grading_batches WHERE batch_id='bprev'").fetchone()[0] == "drained"


def test_drain_prior_leaves_unfinished_batch(db_path):
    conn = _conn(db_path)
    conn.execute(
        "INSERT INTO grading_batches (batch_id, status, job_count) VALUES ('bprev', 'submitted', 1)"
    )
    conn.commit()
    drained = _grader(FakeBatches(status="in_progress")).drain_prior(conn)
    assert drained == 0
    assert conn.execute("SELECT status FROM grading_batches WHERE batch_id='bprev'").fetchone()[0] == "submitted"


# ── run() orchestration ──────────────────────────────────────────────────────
def test_run_disabled_is_noop(db_path, monkeypatch):
    monkeypatch.setattr("job_search.config.settings.GRADING_ENABLED", False)
    batches = FakeBatches()
    stats = _grader(batches).run()
    assert stats["enabled"] is False
    assert batches.created == []  # never submitted


def test_run_timeout_fallback(db_path, monkeypatch):
    monkeypatch.setattr("job_search.config.settings.GRADING_ENABLED", True)
    conn = _conn(db_path)
    _insert(conn, "j1", match_score=0.8)
    conn.close()

    batches = FakeBatches(status="in_progress", batch_id="bnew")
    stats = _grader(batches).run(timeout_s=0)

    assert stats["timed_out"] is True
    assert stats["graded"] == 0
    assert len(batches.created) == 1  # batch WAS submitted

    conn = _conn(db_path)
    # job left ungraded → retried next run
    assert conn.execute("SELECT llm_graded_at FROM jobs WHERE canonical_job_id='j1'").fetchone()[0] is None
    # batch row left 'submitted' → drained next run
    assert conn.execute("SELECT status FROM grading_batches WHERE batch_id='bnew'").fetchone()[0] == "submitted"


def test_run_full_cycle_persists(db_path, monkeypatch):
    monkeypatch.setattr("job_search.config.settings.GRADING_ENABLED", True)
    conn = _conn(db_path)
    _insert(conn, "j1", match_score=0.8)
    conn.close()

    batches = FakeBatches(status="ended", batch_id="bnew", results=[
        _succeeded("j1", {"grade": "Strong", "fit_score": 5, "rationale": "strong fit"}),
    ])
    stats = _grader(batches).run(timeout_s=5)

    assert stats["graded"] == 1
    assert stats["timed_out"] is False
    conn = _conn(db_path)
    assert conn.execute("SELECT llm_grade FROM jobs WHERE canonical_job_id='j1'").fetchone()[0] == "Strong"
    assert conn.execute("SELECT status FROM grading_batches WHERE batch_id='bnew'").fetchone()[0] == "drained"
