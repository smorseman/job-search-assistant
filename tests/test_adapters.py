"""Adapter unit tests — mock HTTP, no live API calls."""

import httpx

from job_search.models import ATSTier, ATSType, FirmConfig


def greenhouse_firm() -> FirmConfig:
    return FirmConfig(
        firm_id="test_firm",
        name="Test Firm",
        ats_type=ATSType.GREENHOUSE,
        ats_tier=ATSTier.GREEN,
        ats_board_token="testfirm",
    )


GREENHOUSE_RESPONSE = {
    "jobs": [
        {
            "id": 12345,
            "title": "Civil Engineer",
            "location": {"name": "Austin, TX"},
            "absolute_url": "https://boards.greenhouse.io/testfirm/jobs/12345",
            "updated_at": "2026-06-01T12:00:00Z",
            "content": "<p>We are looking for a civil engineer with structural design experience.</p>",
        },
        {
            "id": 12346,
            "title": "Software Engineer",  # not civil — should be filtered out
            "location": {"name": "San Francisco, CA"},
            "absolute_url": "https://boards.greenhouse.io/testfirm/jobs/12346",
            "updated_at": "2026-06-01T12:00:00Z",
            "content": "<p>Backend developer role.</p>",
        },
    ]
}


def test_greenhouse_filters_non_civil(respx_mock):
    from job_search.adapters.greenhouse import BASE_URL, GreenhouseAdapter

    firm = greenhouse_firm()
    respx_mock.get(BASE_URL.format(token=firm.ats_board_token)).mock(
        return_value=httpx.Response(200, json=GREENHOUSE_RESPONSE)
    )

    adapter = GreenhouseAdapter(firm)
    jobs = list(adapter.fetch())
    assert len(jobs) == 1
    assert jobs[0].title == "Civil Engineer"
    assert jobs[0].source == "greenhouse"
    assert jobs[0].firm_id == "test_firm"


def test_greenhouse_normalizes_location(respx_mock):
    from job_search.adapters.greenhouse import BASE_URL, GreenhouseAdapter

    firm = greenhouse_firm()
    respx_mock.get(BASE_URL.format(token=firm.ats_board_token)).mock(
        return_value=httpx.Response(200, json=GREENHOUSE_RESPONSE)
    )

    adapter = GreenhouseAdapter(firm)
    jobs = list(adapter.fetch())
    assert jobs[0].location_city == "Austin"
    assert jobs[0].location_state == "TX"


def test_greenhouse_canonical_id_stable(respx_mock):
    from job_search.adapters.greenhouse import BASE_URL, GreenhouseAdapter

    firm = greenhouse_firm()
    respx_mock.get(BASE_URL.format(token=firm.ats_board_token)).mock(
        return_value=httpx.Response(200, json=GREENHOUSE_RESPONSE)
    )

    adapter = GreenhouseAdapter(firm)
    jobs1 = list(adapter.fetch())
    jobs2 = list(adapter.fetch())
    assert jobs1[0].canonical_job_id == jobs2[0].canonical_job_id
