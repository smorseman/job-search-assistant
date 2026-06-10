"""Tests for the location-scoring framework.

Reference values pulled from docs/city_guide.pdf (the analytical model).
Composite tolerances allow ±0.5 to account for rounding differences.
"""

import pytest

from job_search.location import LocationScorer
from job_search.location.matcher import CityMatcher


@pytest.fixture(scope="module")
def scorer():
    return LocationScorer(scheme="balanced")


# ── Composite calculation matches PDF reference values ───────────────────────

@pytest.mark.parametrize(
    "metro_id,scheme,expected",
    [
        ("cleveland_oh",   "balanced",     76.5),
        ("cleveland_oh",   "fit_first",    82.1),
        ("cleveland_oh",   "career_first", 67.9),
        ("cleveland_oh",   "career_only",  57.0),
        ("dc_nova",        "balanced",     71.3),
        ("dc_nova",        "career_first", 70.4),
        ("dc_nova",        "career_only",  75.8),
        ("houston_tx",     "balanced",     68.3),
        ("houston_tx",     "career_relax", 72.7),
        ("nyc_ny",         "balanced",     63.5),
        ("nyc_ny",         "fit_first",    78.8),
        ("sf_bay_ca",      "career_only",  38.7),
    ],
)
def test_composite_matches_pdf(scorer, metro_id, scheme, expected):
    actual = scorer.composite_for(metro_id, scheme=scheme)
    assert abs(actual - expected) < 0.6, (
        f"{metro_id}/{scheme}: expected {expected}, got {actual}"
    )


# ── City matching ────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "city,state,expected_metro_id,expected_kind",
    [
        ("Cleveland",       "OH", "cleveland_oh",     "exact"),
        ("San Bernardino",  "CA", "ie_riverside_ca",  "exact"),
        ("Arlington",       "VA", "dc_nova",          "exact"),
        ("Tysons",          "VA", "dc_nova",          "exact"),
        ("Fort Worth",      "TX", "dallas_fw_tx",     "exact"),
        ("Brooklyn",        "NY", "nyc_ny",           "exact"),
        ("Tempe",           "AZ", "phoenix_tempe_az", "exact"),
        ("Cambridge",       "MA", "boston_ma",        "exact"),
        ("St. Paul",        "MN", "minneapolis_mn",   "exact"),
        ("Jersey City",     "NJ", "nyc_ny",           "exact"),
        ("Inland Empire",   "CA", "ie_riverside_ca",  "alias"),
    ],
)
def test_city_alias_matching(scorer, city, state, expected_metro_id, expected_kind):
    s = scorer.score(city, state)
    assert s.metro_id == expected_metro_id
    assert s.match_kind == expected_kind
    assert s.ranked is True


def test_fuzzy_match_on_typo(scorer):
    s = scorer.score("Cinncinati", "OH")    # misspelled
    assert s.metro_id == "cincinnati_oh"
    assert s.match_kind == "fuzzy"
    assert 0.8 <= s.confidence < 1.0


def test_unranked_metro_returns_fallback(scorer):
    s = scorer.score("Boise", "ID")
    assert s.metro_id is None
    assert s.ranked is False
    assert s.match_kind == "fallback"
    assert s.composite == 40.0


def test_remote_classified_as_remote(scorer):
    s = scorer.score("Remote", None)
    assert s.metro_id is None
    assert s.match_kind == "remote"


def test_empty_city_classified_as_remote(scorer):
    s = scorer.score(None, "CA")
    assert s.match_kind == "remote"


# ── Scheme switching changes the composite ───────────────────────────────────

def test_scheme_changes_composite():
    """Houston favors career; Cleveland favors lifestyle. Different schemes should reverse the order."""
    sc_balanced = LocationScorer(scheme="balanced")
    sc_career   = LocationScorer(scheme="career_only")

    cleveland_bal = sc_balanced.composite_for("cleveland_oh")
    houston_bal   = sc_balanced.composite_for("houston_tx")
    cleveland_car = sc_career.composite_for("cleveland_oh")
    houston_car   = sc_career.composite_for("houston_tx")

    assert cleveland_bal > houston_bal, "Cleveland should lead under balanced"
    assert houston_car > cleveland_car, "Houston should lead under career_only"


def test_invalid_scheme_rejected():
    with pytest.raises(ValueError, match="not defined"):
        LocationScorer(scheme="bogus_scheme")  # type: ignore[arg-type]


# ── Normalization helper ─────────────────────────────────────────────────────

def test_location_score_normalized_property(scorer):
    s = scorer.score("Cleveland", "OH")
    assert 0.0 <= s.normalized <= 1.0
    assert abs(s.normalized - s.composite / 100.0) < 1e-9
