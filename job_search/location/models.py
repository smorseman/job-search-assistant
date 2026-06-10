"""Data models for the location-scoring framework.

Dimensions and schemes follow docs/city_guide.pdf (May 2026).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


SchemeName = Literal["fit_first", "balanced", "career_relax", "career_first", "career_only"]
DEFAULT_SCHEME: SchemeName = "balanced"


@dataclass(frozen=True)
class DimensionScores:
    """0–5 score on each of the five dimensions."""
    ce: float = 0.0
    col: float = 0.0
    home: float = 0.0
    mj: float = 0.0
    dating: float = 0.0

    def weighted_sum(self, weights: dict[str, float]) -> float:
        return (
            weights.get("ce", 0)     * self.ce +
            weights.get("col", 0)    * self.col +
            weights.get("home", 0)   * self.home +
            weights.get("mj", 0)     * self.mj +
            weights.get("dating", 0) * self.dating
        )


@dataclass(frozen=True)
class MetroArea:
    """One ranked metro area + all its supplementary data."""
    id: str
    name: str
    state: str
    balanced_rank: int | None
    aliases: tuple[str, ...] = ()
    scores: DimensionScores = field(default_factory=DimensionScores)
    # Supplementary inputs (kept for reporting / future re-scoring)
    population_m: float | None = None
    salary_k: int | None = None
    real_net_k: int | None = None
    rpp: float | None = None
    rent_1br: int | None = None
    solo_savings: int | None = None
    starter_home_k: int | None = None
    years_20pct_solo: float | None = None
    entry_jobs: int | None = None
    total_jobs: int | None = None
    ce_raw: float | None = None
    cannabis_status: str | None = None
    wm_index: int | None = None
    pct_pop_25_34: float | None = None


@dataclass(frozen=True)
class LocationScore:
    """Result of scoring a (city, state) against the metro framework."""
    metro_id: str | None              # None if unranked / unmatched
    metro_name: str | None
    composite: float                   # 0–100
    dimensions: DimensionScores
    scheme: SchemeName
    ranked: bool                       # False when fallback was used
    match_kind: str                    # "exact" | "alias" | "fuzzy" | "fallback" | "remote"
    confidence: float                  # 0.0–1.0 — match confidence

    @property
    def normalized(self) -> float:
        """Composite mapped to 0.0–1.0 for use in match-score contribution."""
        return max(0.0, min(self.composite / 100.0, 1.0))
