"""Match scoring engine.

Produces a 0.0–1.0 match_score and a stretch_category for each job.
Also computes benefit_score and career_trajectory_score.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from job_search.models import CanonicalJob, StretchCategory


# ── Discipline weights (from profile — can be overridden via config) ──────────
DISCIPLINE_WEIGHTS: dict[str, float] = {
    "structural": 1.0,
    "construction_engineering": 0.8,
    "construction_management": 0.8,
    "land_development": 0.7,
    "site_civil": 0.7,
    "transportation": 0.6,
    "municipal": 0.6,
    "water_resources": 0.5,
    "environmental": 0.5,
    "geotechnical": 0.5,
    "federal": 0.5,
}

# ── Metro premiums ────────────────────────────────────────────────────────────
PREMIUM_STATE_ABBREVS = {"NY", "CA", "WA", "OR", "CO", "MA", "FL", "SC", "AK"}
PREMIUM_METRO_KEYWORDS = [
    "new york", "los angeles", "seattle", "portland", "denver",
    "san francisco", "boston", "miami", "charleston", "anchorage",
]
COASTAL_MOUNTAIN_KEYWORDS = [
    "coastal", "waterfront", "harbor", "bay", "gulf", "ocean",
    "mountain", "alpine", "rocky", "sierra", "cascade",
    "pacific", "atlantic",
]

# ── Benefit keywords → benefit_score bump ────────────────────────────────────
BENEFIT_SIGNALS: dict[str, float] = {
    "relocation": 0.08,
    "signing bonus": 0.06,
    "tuition": 0.10,
    "graduate": 0.08,
    "fe exam": 0.05,
    "pe exam": 0.07,
    "pe prep": 0.07,
    "licensing": 0.05,
    "continuing education": 0.05,
    "student loan": 0.05,
    "housing": 0.04,
}

# ── Career trajectory signals ─────────────────────────────────────────────────
TRAJECTORY_SIGNALS: dict[str, float] = {
    "pe track": 0.10,
    "engineer in training": 0.08,
    "eit": 0.06,
    "mentorship": 0.08,
    "mentor": 0.06,
    "design responsibility": 0.07,
    "rotational": 0.08,
    "promotion": 0.05,
    "advancement": 0.05,
    "graduate study": 0.07,
    "tuition": 0.07,
    "leadership development": 0.07,
    "large project": 0.05,
    "significant project": 0.05,
}

# ── Degree requirement patterns ───────────────────────────────────────────────
DEGREE_EXACT = re.compile(r"\bbs\s+civil\s+engineering\b", re.IGNORECASE)
DEGREE_RELATED = re.compile(
    r"\b(civil engineering technology|construction engineering|bachelor.*engineer)\b",
    re.IGNORECASE,
)


@dataclass
class ScoringContext:
    """Enriched view of a job for the scoring engine."""
    text: str = ""                  # combined title + description (lowercased)
    discipline: str = "unknown"
    discipline_weight: float = 0.5
    geo_premium: float = 0.0
    knockout_ok: bool = True
    knockout_issues: list[str] = field(default_factory=list)
    benefit_score: float = 0.0
    trajectory_score: float = 0.0
    stretch_category: StretchCategory = StretchCategory.QUALIFIED


class Scorer:
    def score(self, job: CanonicalJob) -> CanonicalJob:
        ctx = self._build_context(job)
        job.match_score = self._compute_match_score(ctx)
        job.benefit_score = ctx.benefit_score
        job.career_trajectory_score = ctx.trajectory_score
        job.stretch_category = ctx.stretch_category
        return job

    def _build_context(self, job: CanonicalJob) -> ScoringContext:
        ctx = ScoringContext()
        ctx.text = (
            (job.title or "") + " " +
            (job.description_normalized or "") + " " +
            (job.location_city or "") + " " +
            (job.location_state or "")
        ).lower()

        ctx.discipline, ctx.discipline_weight = self._detect_discipline(ctx.text)
        ctx.geo_premium = self._geo_premium(job)
        ctx.knockout_ok, ctx.knockout_issues = self._check_knockouts(job)
        ctx.benefit_score = self._compute_benefit_score(ctx.text)
        ctx.trajectory_score = self._compute_trajectory_score(ctx.text)
        ctx.stretch_category = self._classify_stretch(job, ctx.text)
        return ctx

    def _detect_discipline(self, text: str) -> tuple[str, float]:
        scores: dict[str, float] = {}
        if "structural" in text or "ram" in text or "seismic" in text:
            scores["structural"] = DISCIPLINE_WEIGHTS["structural"]
        if "construction management" in text or "construction manager" in text:
            scores["construction_management"] = DISCIPLINE_WEIGHTS["construction_management"]
        if "construction engineer" in text or "field engineer" in text:
            scores["construction_engineering"] = DISCIPLINE_WEIGHTS["construction_engineering"]
        if "land development" in text or "site civil" in text or "site design" in text:
            scores["land_development"] = DISCIPLINE_WEIGHTS["land_development"]
        if "transportation" in text or "highway" in text or "roadway" in text:
            scores["transportation"] = DISCIPLINE_WEIGHTS["transportation"]
        if "water resource" in text or "hydraulic" in text or "hydrology" in text or "hec-ras" in text:
            scores["water_resources"] = DISCIPLINE_WEIGHTS["water_resources"]
        if "environmental" in text:
            scores["environmental"] = DISCIPLINE_WEIGHTS["environmental"]
        if "geotechnical" in text or "geotech" in text or "soil" in text:
            scores["geotechnical"] = DISCIPLINE_WEIGHTS["geotechnical"]
        if "municipal" in text or "public works" in text:
            scores["municipal"] = DISCIPLINE_WEIGHTS["municipal"]

        if not scores:
            return "civil", 0.5
        best = max(scores, key=lambda k: scores[k])
        return best, scores[best]

    def _geo_premium(self, job: CanonicalJob) -> float:
        state = (job.location_state or "").upper()
        city = (job.location_city or "").lower()
        desc = (job.description_normalized or "").lower()

        premium = 0.0
        if state in PREMIUM_STATE_ABBREVS:
            premium += 0.05
        if any(kw in city for kw in PREMIUM_METRO_KEYWORDS):
            premium += 0.05
        if any(kw in desc or kw in city for kw in COASTAL_MOUNTAIN_KEYWORDS):
            premium += 0.03
        return min(premium, 0.12)

    def _check_knockouts(self, job: CanonicalJob) -> tuple[bool, list[str]]:
        ko = job.knockout
        issues: list[str] = []

        # PE required — James not yet eligible
        if ko.pe_required:
            issues.append("PE license required — not yet eligible")

        # Minimum years experience
        if ko.min_years and ko.min_years > 2:
            issues.append(f"Min {ko.min_years:.0f} years required — new grad")

        # Clearance
        if ko.clearance and ko.clearance.lower() not in ("none", ""):
            issues.append(f"Security clearance required: {ko.clearance}")

        return len(issues) == 0, issues

    def _compute_benefit_score(self, text: str) -> float:
        score = 0.0
        for signal, bump in BENEFIT_SIGNALS.items():
            if signal in text:
                score += bump
        return min(score, 0.40)

    def _compute_trajectory_score(self, text: str) -> float:
        score = 0.0
        for signal, bump in TRAJECTORY_SIGNALS.items():
            if signal in text:
                score += bump
        return min(score, 0.40)

    def _classify_stretch(self, job: CanonicalJob, text: str) -> StretchCategory:
        """
        Qualified: meets degree or equivalent stated; no hard degree mismatch.
        Competitive Stretch: requires "BS Civil Engineering" but CET may be accepted.
        Long Shot: significant mismatch.
        """
        if DEGREE_RELATED.search(text):
            return StretchCategory.QUALIFIED

        if DEGREE_EXACT.search(text):
            # Many firms that list BS CE will accept CET — mark as stretch, not excluded
            return StretchCategory.COMPETITIVE_STRETCH

        # PE required with no years is a hard stretch
        if job.knockout.pe_required:
            return StretchCategory.LONG_SHOT

        if job.knockout.min_years and job.knockout.min_years >= 5:
            return StretchCategory.LONG_SHOT

        return StretchCategory.QUALIFIED

    def _compute_match_score(self, ctx: ScoringContext) -> float:
        if not ctx.knockout_ok:
            base = 0.25  # still surfaced but flagged
        else:
            base = 0.50

        # Discipline contribution (up to 0.30)
        discipline_contribution = ctx.discipline_weight * 0.30

        # Geo contribution (up to 0.12)
        geo_contribution = ctx.geo_premium

        # Benefit & trajectory (up to 0.10 each, scaled down to contribute ~0.08)
        benefit_contribution = ctx.benefit_score * 0.20
        trajectory_contribution = ctx.trajectory_score * 0.20

        raw = base + discipline_contribution + geo_contribution + benefit_contribution + trajectory_contribution

        # Stretch penalty
        if ctx.stretch_category == StretchCategory.COMPETITIVE_STRETCH:
            raw *= 0.90
        elif ctx.stretch_category == StretchCategory.LONG_SHOT:
            raw *= 0.70

        return round(min(max(raw, 0.0), 1.0), 4)
