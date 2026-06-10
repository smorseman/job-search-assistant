"""Score a job posting's location against the metro framework.

Loads cities.yaml once per process, then provides a fast lookup +
scheme-based composite score for every posting.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .matcher import CityMatcher
from .models import DEFAULT_SCHEME, DimensionScores, LocationScore, MetroArea, SchemeName

logger = logging.getLogger(__name__)

DEFAULT_CITIES_PATH = "config/cities.yaml"


class LocationScorer:
    def __init__(
        self,
        scheme: SchemeName = DEFAULT_SCHEME,
        cities_path: str = DEFAULT_CITIES_PATH,
    ):
        self.scheme: SchemeName = scheme
        self._cities_path = cities_path
        self._raw = self._load_yaml(cities_path)
        self._metros = self._parse_metros(self._raw)
        self._schemes = self._raw.get("schemes", {})
        self._fallback = float(self._raw.get("fallback_composite", 40.0))
        self.matcher = CityMatcher(self._metros)
        self._validate_scheme(scheme)

    def score(self, city: str | None, state: str | None = None) -> LocationScore:
        """Score a posting location. Returns a LocationScore (never raises)."""
        result = self.matcher.match(city, state)

        if result is None:
            # Distinguish remote/no-location vs unranked-metro for reporting
            remote_markers = {"remote", "anywhere", "multiple locations", "various", "us remote"}
            is_remote = (
                not city
                or not city.strip()
                or city.strip().lower() in remote_markers
            )
            return LocationScore(
                metro_id=None,
                metro_name=None,
                composite=self._fallback,
                dimensions=DimensionScores(),
                scheme=self.scheme,
                ranked=False,
                match_kind="remote" if is_remote else "fallback",
                confidence=0.0,
            )

        composite = self._compute_composite(result.metro.scores, self.scheme)
        return LocationScore(
            metro_id=result.metro.id,
            metro_name=result.metro.name,
            composite=composite,
            dimensions=result.metro.scores,
            scheme=self.scheme,
            ranked=True,
            match_kind=result.kind,
            confidence=result.confidence,
        )

    def composite_for(self, metro_id: str, scheme: SchemeName | None = None) -> float:
        """Look up composite by metro_id under a given scheme."""
        scheme_name: SchemeName = scheme or self.scheme
        metro = next((m for m in self._metros if m.id == metro_id), None)
        if not metro:
            return self._fallback
        return self._compute_composite(metro.scores, scheme_name)

    def _compute_composite(self, scores: DimensionScores, scheme: SchemeName) -> float:
        weights = self._schemes[scheme]
        weighted = scores.weighted_sum(weights)
        total_weight = sum(weights.values())
        if total_weight <= 0:
            return self._fallback
        return round(weighted / (total_weight * 5) * 100, 2)

    def _validate_scheme(self, scheme: SchemeName) -> None:
        if scheme not in self._schemes:
            raise ValueError(
                f"Scheme '{scheme}' not defined in {self._cities_path}. "
                f"Available: {sorted(self._schemes.keys())}"
            )

    def _load_yaml(self, path: str) -> dict[str, Any]:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"cities.yaml not found at {path}")
        with open(p) as f:
            return yaml.safe_load(f) or {}

    def _parse_metros(self, raw: dict[str, Any]) -> list[MetroArea]:
        metros = []
        for entry in raw.get("cities", []):
            scores = DimensionScores(**(entry.get("scores") or {}))
            metros.append(MetroArea(
                id=entry["id"],
                name=entry["name"],
                state=entry["state"],
                balanced_rank=entry.get("balanced_rank"),
                aliases=tuple(entry.get("aliases") or []),
                scores=scores,
                population_m=entry.get("population_m"),
                salary_k=entry.get("salary_k"),
                real_net_k=entry.get("real_net_k"),
                rpp=entry.get("rpp"),
                rent_1br=entry.get("rent_1br"),
                solo_savings=entry.get("solo_savings"),
                starter_home_k=entry.get("starter_home_k"),
                years_20pct_solo=entry.get("years_20pct_solo"),
                entry_jobs=entry.get("entry_jobs"),
                total_jobs=entry.get("total_jobs"),
                ce_raw=entry.get("ce_raw"),
                cannabis_status=entry.get("cannabis_status"),
                wm_index=entry.get("wm_index"),
                pct_pop_25_34=entry.get("pct_pop_25_34"),
            ))
        logger.info("Loaded %d metro areas from %s", len(metros), self._cities_path)
        return metros


# Module-level cache so the scorer is loaded once per process
@lru_cache(maxsize=4)
def get_location_scorer(scheme: SchemeName = DEFAULT_SCHEME) -> LocationScorer:
    return LocationScorer(scheme=scheme)
