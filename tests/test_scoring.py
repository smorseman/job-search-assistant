"""Tests for match scoring engine."""

import pytest

from job_search.ingestion.scoring import Scorer
from job_search.models import CanonicalJob, StretchCategory


def make_job(**kwargs) -> CanonicalJob:
    defaults = dict(
        source="test",
        source_job_id="s001",
        company="Acme",
        title="Structural Engineer",
        description_normalized="structural design RAM Structural System steel design reinforced concrete engineer in training EIT tuition reimbursement mentorship",
        location_city="Seattle",
        location_state="WA",
    )
    defaults.update(kwargs)
    return CanonicalJob(**defaults)


def test_structural_seattle_high_score():
    scorer = Scorer()
    job = make_job()
    job = scorer.score(job)
    assert job.match_score is not None
    assert job.match_score >= 0.70, f"Expected high score, got {job.match_score}"


def test_benefit_score_captured():
    scorer = Scorer()
    job = make_job()
    job = scorer.score(job)
    assert job.benefit_score > 0.0


def test_trajectory_score_captured():
    scorer = Scorer()
    job = make_job()
    job = scorer.score(job)
    assert job.career_trajectory_score > 0.0


def test_pe_required_penalty():
    scorer = Scorer()
    from job_search.models import KnockoutFields
    job = make_job(
        title="Senior Structural Engineer",
        description_normalized="PE required professional engineer license 10 years experience",
    )
    job.knockout = KnockoutFields(pe_required=True, min_years=10)
    job = scorer.score(job)
    assert job.match_score < 0.50


def test_stretch_category_bs_ce():
    scorer = Scorer()
    job = make_job(
        description_normalized="BS Civil Engineering required structural design"
    )
    job = scorer.score(job)
    assert job.stretch_category == StretchCategory.COMPETITIVE_STRETCH


def test_qualified_with_cet():
    scorer = Scorer()
    job = make_job(
        description_normalized="civil engineering technology bachelor degree structural"
    )
    job = scorer.score(job)
    assert job.stretch_category == StretchCategory.QUALIFIED
