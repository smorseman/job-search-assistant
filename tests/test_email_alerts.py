"""Tests for the email-alert parser — uses synthetic HTML, no live Gmail."""

import pytest

from job_search.adapters.email_alerts import EmailAlertsAdapter, RawAlert


@pytest.fixture
def adapter():
    a = EmailAlertsAdapter.__new__(EmailAlertsAdapter)
    return a


# ── LinkedIn alert parsing ───────────────────────────────────────────────────

LINKEDIN_HTML = (
    '<html><body>'
    '<p>New jobs for "Civil Engineer"</p>'
    '<a href="https://www.linkedin.com/comm/jobs/view/3892145678/?refId=abc">Civil Engineer</a>'
    '<span>Kimley-Horn · Austin, TX</span>'
    '<a href="https://www.linkedin.com/comm/jobs/view/3892145679/?refId=def">Structural Engineer I</a>'
    '<span>Walter P Moore · Houston, TX</span>'
    '<a href="https://www.linkedin.com/comm/jobs/view/3892145680/?refId=ghi">Software Engineer</a>'
    '<span>Acme Tech · San Francisco, CA</span>'
    '</body></html>'
)


def test_linkedin_extracts_civil_jobs(adapter):
    alerts = list(adapter._parse_linkedin(LINKEDIN_HTML, "msg1", "linkedin.com"))
    assert len(alerts) == 3
    titles = [a.title for a in alerts]
    assert "Civil Engineer" in titles
    assert "Structural Engineer I" in titles


def test_linkedin_url_canonicalized(adapter):
    alerts = list(adapter._parse_linkedin(LINKEDIN_HTML, "msg1", "linkedin.com"))
    for a in alerts:
        assert a.url.startswith("https://www.linkedin.com/jobs/view/")
        assert a.url.endswith("/")


def test_linkedin_company_location_extracted(adapter):
    alerts = list(adapter._parse_linkedin(LINKEDIN_HTML, "msg1", "linkedin.com"))
    civil = next(a for a in alerts if a.title == "Civil Engineer")
    assert civil.company == "Kimley-Horn"
    assert civil.location == "Austin, TX"


# ── Indeed alert parsing ─────────────────────────────────────────────────────

INDEED_HTML = """
<a href="https://www.indeed.com/viewjob?jk=abc123def456&xyz=1">Structural Engineer</a>
<div>HDR · Seattle, WA</div>
<a href="https://www.indeed.com/rc/clk?jk=def789ghi012">Construction Manager</a>
<div>Skanska · Boston, MA</div>
"""


def test_indeed_extracts_jobs(adapter):
    alerts = list(adapter._parse_indeed(INDEED_HTML, "msg2", "indeed.com"))
    titles = {a.title for a in alerts}
    assert "Structural Engineer" in titles


def test_indeed_url_normalized(adapter):
    alerts = list(adapter._parse_indeed(INDEED_HTML, "msg2", "indeed.com"))
    for a in alerts:
        assert a.url == f"https://www.indeed.com/viewjob?jk={a.message_id.split(':')[1]}"


# ── Civil-relevance filter ───────────────────────────────────────────────────

def test_non_civil_skipped(adapter):
    alert = RawAlert(
        title="Senior Backend Engineer",
        company="Acme",
        location="Austin, TX",
        url="https://example.com/job",
        snippet="Python, Go, distributed systems",
        sender_domain="linkedin.com",
        message_id="x:1",
    )
    job = adapter._to_canonical_job(alert)
    assert job is None


def test_civil_kept(adapter):
    alert = RawAlert(
        title="Civil Engineer",
        company="Kimley-Horn",
        location="Austin, TX",
        url="https://example.com/job",
        snippet="Structural design, AutoCAD Civil 3D",
        sender_domain="linkedin.com",
        message_id="linkedin:123",
    )
    job = adapter._to_canonical_job(alert)
    assert job is not None
    assert job.title == "Civil Engineer"
    assert job.company == "Kimley-Horn"
    assert job.location_city == "Austin"
    assert job.location_state == "TX"
    assert job.source == "email_alert"


# ── Generic fallback ─────────────────────────────────────────────────────────

GENERIC_HTML = """
<a href="https://example.com/careers/openings/jr-civil-engineer">Junior Civil Engineer</a>
<p>Engineering Co · Denver, CO</p>
"""


def test_generic_parser_finds_job_link(adapter):
    alerts = list(adapter._parse_generic(GENERIC_HTML, "msg3", "engcareers.com"))
    assert len(alerts) >= 1
    assert any("civil" in a.title.lower() for a in alerts)
