"""Match scoring engine.

Produces a 0.0–1.0 match_score and a stretch_category for each job.
Also computes benefit_score, career_trajectory_score, and attaches a
LocationScore from the city-guide framework.

Weights are configurable in config/scoring.yaml.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from job_search.location import LocationScore, LocationScorer
from job_search.location.models import SchemeName
from job_search.models import CanonicalJob, StretchCategory

logger = logging.getLogger(__name__)


# ── Discipline detection (used by Scorer) ─────────────────────────────────────
# Defaults; can be overridden by config/scoring.yaml -> discipline_weights
DEFAULT_DISCIPLINE_WEIGHTS: dict[str, float] = {
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

DEFAULT_MATCH_FORMULA = {
    "base": 0.25,
    "discipline_weight": 0.25,
    "location_weight": 0.30,
    "benefit_weight": 0.10,
    "trajectory_weight": 0.10,
}

# ── Benefit keywords → benefit_score contribution ────────────────────────────
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
    text: str = ""
    discipline: str = "unknown"
    discipline_weight: float = 0.5
    location: LocationScore | None = None
    knockout_ok: bool = True
    knockout_issues: list[str] = field(default_factory=list)
    benefit_score: float = 0.0
    trajectory_score: float = 0.0
    stretch_category: StretchCategory = StretchCategory.QUALIFIED


class Scorer:
    def __init__(self, config_path: str = "config/scoring.yaml"):
        cfg = self._load_config(config_path)
        self.discipline_weights = {
            **DEFAULT_DISCIPLINE_WEIGHTS,
            **(cfg.get("discipline_weights") or {}),
        }
        self.formula = {**DEFAULT_MATCH_FORMULA, **(cfg.get("match_formula") or {})}
        loc_cfg = cfg.get("location") or {}
        scheme: SchemeName = loc_cfg.get("scheme", "balanced")
        try:
            self.location_scorer: LocationScorer | None = LocationScorer(scheme=scheme)
        except FileNotFoundError:
            logger.warning("cities.yaml not found — location scoring disabled")
            self.location_scorer = None

    def score(self, job: CanonicalJob) -> CanonicalJob:
        ctx = self._build_context(job)
        job.match_score = self._compute_match_score(ctx)
        job.benefit_score = ctx.benefit_score
        job.career_trajectory_score = ctx.trajectory_score
        job.stretch_category = ctx.stretch_category
        return job

    def score_location(self, job: CanonicalJob) -> LocationScore | None:
        """Public: get the LocationScore for a job (used by reporting)."""
        if not self.location_scorer:
            return None
        return self.location_scorer.score(job.location_city, job.location_state)

    def _build_context(self, job: CanonicalJob) -> ScoringContext:
        ctx = ScoringContext()
        ctx.text = (
            (job.title or "") + " " +
            (job.description_normalized or "") + " " +
            (job.location_city or "") + " " +
            (job.location_state or "")
        ).lower()

        ctx.discipline, ctx.discipline_weight = self._detect_discipline(ctx.text)
        if self.location_scorer:
            ctx.location = self.location_scorer.score(job.location_city, job.location_state)
        ctx.knockout_ok, ctx.knockout_issues = self._check_knockouts(job)
        ctx.benefit_score = self._compute_benefit_score(ctx.text)
        ctx.trajectory_score = self._compute_trajectory_score(ctx.text)
        ctx.stretch_category = self._classify_stretch(job, ctx.text)
        return ctx

    def _detect_discipline(self, text: str) -> tuple[str, float]:
        scores: dict[str, float] = {}
        w = self.discipline_weights
        if "structural" in text or "ram structural" in text or "seismic" in text:
            scores["structural"] = w["structural"]
        if "construction management" in text or "construction manager" in text:
            scores["construction_management"] = w["construction_management"]
        if "construction engineer" in text or "field engineer" in text:
            scores["construction_engineering"] = w["construction_engineering"]
        if "land development" in text or "site civil" in text or "site design" in text:
            scores["land_development"] = w["land_development"]
        if "transportation" in text or "highway" in text or "roadway" in text:
            scores["transportation"] = w["transportation"]
        if "water resource" in text or "hydraulic" in text or "hydrology" in text or "hec-ras" in text:
            scores["water_resources"] = w["water_resources"]
        if "environmental" in text:
            scores["environmental"] = w["environmental"]
        if "geotechnical" in text or "geotech" in text or " soil" in text:
            scores["geotechnical"] = w["geotechnical"]
        if "municipal" in text or "public works" in text:
            scores["municipal"] = w["municipal"]

        if not scores:
            return "civil", 0.5
        best = max(scores, key=lambda k: scores[k])
        return best, scores[best]

    def _check_knockouts(self, job: CanonicalJob) -> tuple[bool, list[str]]:
        ko = job.knockout
        issues: list[str] = []
        if ko.pe_required:
            issues.append("PE license required — not yet eligible")
        if ko.min_years and ko.min_years > 2:
            issues.append(f"Min {ko.min_years:.0f} years required — new grad")
        if ko.clearance and ko.clearance.lower() not in ("none", ""):
            issues.append(f"Security clearance required: {ko.clearance}")
        return len(issues) == 0, issues

    def _compute_benefit_score(self, text: str) -> float:
        score = 0.0
        for signal, bump in BENEFIT_SIGNALS.items():
            if signal in text:
                score += bump
        return min(score, 1.0)

    def _compute_trajectory_score(self, text: str) -> float:
        score = 0.0
        for signal, bump in TRAJECTORY_SIGNALS.items():
            if signal in text:
                score += bump
        return min(score, 1.0)

    def _classify_stretch(self, job: CanonicalJob, text: str) -> StretchCategory:
        if DEGREE_RELATED.search(text):
            return StretchCategory.QUALIFIED
        if DEGREE_EXACT.search(text):
            return StretchCategory.COMPETITIVE_STRETCH
        if job.knockout.pe_required:
            return StretchCategory.LONG_SHOT
        if job.knockout.min_years and job.knockout.min_years >= 5:
            return StretchCategory.LONG_SHOT
        return StretchCategory.QUALIFIED

    def _compute_match_score(self, ctx: ScoringContext) -> float:
        f = self.formula
        base = f["base"] * (0.5 if not ctx.knockout_ok else 1.0)

        discipline_contribution = ctx.discipline_weight * f["discipline_weight"]
        location_contribution = (
            ctx.location.normalized * f["location_weight"]
            if ctx.location else 0.4 * f["location_weight"]   # fallback if no scorer
        )
        benefit_contribution = ctx.benefit_score * f["benefit_weight"]
        trajectory_contribution = ctx.trajectory_score * f["trajectory_weight"]

        raw = (
            base
            + discipline_contribution
            + location_contribution
            + benefit_contribution
            + trajectory_contribution
        )

        # Stretch penalty
        if ctx.stretch_category == StretchCategory.COMPETITIVE_STRETCH:
            raw *= 0.92
        elif ctx.stretch_category == StretchCategory.LONG_SHOT:
            raw *= 0.75

        return round(min(max(raw, 0.0), 1.0), 4)

    def _load_config(self, path: str) -> dict:
        p = Path(path)
        if not p.exists():
            return {}
        with open(p) as f:
            return yaml.safe_load(f) or {}
