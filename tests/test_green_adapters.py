"""Smoke tests for the four new Green-tier adapters using mocked HTTP."""

import httpx
import pytest

from job_search.models import ATSTier, ATSType, FirmConfig


@pytest.fixture
def firm():
    return FirmConfig(
        firm_id="test_firm",
        name="Test Firm",
        ats_tier=ATSTier.GREEN,
        ats_board_token="testfirm",
    )


# ── Ashby ────────────────────────────────────────────────────────────────────

ASHBY_RESPONSE = {
    "jobs": [
        {
            "id": "ash_001",
            "title": "Civil Engineer I",
            "locationName": "Austin, TX",
            "descriptionPlain": "Structural design experience required.",
            "jobUrl": "https://jobs.ashbyhq.com/testfirm/civil",
            "publishedAt": "2026-06-01T00:00:00Z",
            "isRemote": False,
        },
        {
            "id": "ash_002",
            "title": "Backend Engineer",   # not civil; should be filtered
            "locationName": "Remote",
            "descriptionPlain": "Python, distributed systems",
            "jobUrl": "https://jobs.ashbyhq.com/testfirm/be",
            "isRemote": True,
        },
    ]
}


def test_ashby_normalizes_and_filters(respx_mock, firm):
    from job_search.adapters.ashby import BASE_URL, AshbyAdapter
    firm.ats_type = ATSType.ASHBY
    respx_mock.get(BASE_URL.format(token="testfirm")).mock(
        return_value=httpx.Response(200, json=ASHBY_RESPONSE)
    )
    jobs = list(AshbyAdapter(firm).fetch())
    assert len(jobs) == 1
    assert jobs[0].title == "Civil Engineer I"
    assert jobs[0].source == "ashby"
    assert jobs[0].location_city == "Austin"
    assert jobs[0].location_state == "TX"
    assert jobs[0].posted_date == "2026-06-01"


# ── SmartRecruiters ──────────────────────────────────────────────────────────

SMARTRECRUITERS_RESPONSE = {
    "totalFound": 2,
    "content": [
        {
            "id": "sr_001",
            "name": "Civil Engineer - Transportation",
            "location": {"city": "Denver", "region": "CO", "country": "us"},
            "releasedDate": "2026-06-02T12:00:00Z",
        },
        {
            "id": "sr_002",
            "name": "Marketing Manager",
            "location": {"city": "Boston", "region": "MA"},
        },
    ],
}


def test_smartrecruiters_filters_non_civil(respx_mock, firm):
    from job_search.adapters.smartrecruiters import LIST_URL, SmartRecruitersAdapter
    firm.ats_type = ATSType.SMARTRECRUITERS
    respx_mock.get(LIST_URL.format(company="testfirm")).mock(
        return_value=httpx.Response(200, json=SMARTRECRUITERS_RESPONSE)
    )
    jobs = list(SmartRecruitersAdapter(firm).fetch())
    assert len(jobs) == 1
    assert "Civil Engineer" in jobs[0].title
    assert jobs[0].location_state == "CO"


# ── Workable ─────────────────────────────────────────────────────────────────

WORKABLE_RESPONSE = {
    "results": [
        {
            "shortcode": "wkbl_001",
            "title": "Site Civil Engineer",
            "description": "<p>Land development experience required</p>",
            "location": {"city": "Tampa", "region": "FL"},
            "remote": False,
            "published": "2026-06-03",
        },
    ]
}


def test_workable_strips_html_and_normalizes(respx_mock, firm):
    from job_search.adapters.workable import LIST_URL, WorkableAdapter
    firm.ats_type = ATSType.WORKABLE
    respx_mock.get(LIST_URL.format(subdomain="testfirm")).mock(
        return_value=httpx.Response(200, json=WORKABLE_RESPONSE)
    )
    jobs = list(WorkableAdapter(firm).fetch())
    assert len(jobs) == 1
    assert jobs[0].title == "Site Civil Engineer"
    assert "<p>" not in (jobs[0].description_normalized or "")
    assert jobs[0].apply_url == "https://apply.workable.com/testfirm/j/wkbl_001/"


# ── Recruitee ────────────────────────────────────────────────────────────────

RECRUITEE_RESPONSE = {
    "offers": [
        {
            "id": 555,
            "title": "Structural Engineer",
            "description": "<p>Steel and reinforced concrete</p>",
            "city": "Seattle",
            "state_code": "WA",
            "country_code": "US",
            "remote": False,
            "careers_url": "https://testfirm.recruitee.com/o/structural-engineer",
            "published_at": "2026-06-04T00:00:00Z",
        },
    ]
}


def test_recruitee_normalizes(respx_mock, firm):
    from job_search.adapters.recruitee import LIST_URL, RecruiteeAdapter
    firm.ats_type = ATSType.RECRUITEE
    respx_mock.get(LIST_URL.format(subdomain="testfirm")).mock(
        return_value=httpx.Response(200, json=RECRUITEE_RESPONSE)
    )
    jobs = list(RecruiteeAdapter(firm).fetch())
    assert len(jobs) == 1
    assert jobs[0].title == "Structural Engineer"
    assert jobs[0].location_city == "Seattle"
    assert jobs[0].location_state == "WA"


# ── ATS_ADAPTER_MAP sanity ────────────────────────────────────────────────────

def test_ats_adapter_map_covers_all_green_types():
    from job_search.adapters import ATS_ADAPTER_MAP
    green = {ATSType.GREENHOUSE, ATSType.LEVER, ATSType.ASHBY,
             ATSType.SMARTRECRUITERS, ATSType.WORKABLE, ATSType.RECRUITEE}
    assert green.issubset(ATS_ADAPTER_MAP.keys())
