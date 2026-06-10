"""Match a (city, state) string to a canonical MetroArea.

Resolution order:
  1. Exact: name or alias exact-match (normalized lower/strip).
  2. Alias-with-state: alias match within the same state.
  3. Fuzzy: rapidfuzz token_sort_ratio against name + aliases.
  4. Remote / no-location: returns None with match_kind="remote".

State-only inputs (e.g., city is None) return None — we don't guess which
metro within a state the job is in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz, process

from .models import MetroArea


# Fuzzy-match threshold — below this, fall through to fallback
FUZZY_THRESHOLD = 88


@dataclass
class MatchResult:
    metro: MetroArea
    kind: str               # "exact" | "alias" | "fuzzy"
    confidence: float       # 0.0–1.0


class CityMatcher:
    def __init__(self, metros: list[MetroArea]):
        self.metros = metros
        self._by_id: dict[str, MetroArea] = {m.id: m for m in metros}
        self._lookup, self._state_lookup = self._build_lookups(metros)

    def _build_lookups(
        self, metros: list[MetroArea]
    ) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
        """
        Build two indexes:
          - global lookup: normalized key → metro_id  (for exact/alias)
          - per-state lookup: state → {key → metro_id}
        """
        global_lookup: dict[str, str] = {}
        state_lookup: dict[str, dict[str, str]] = {}

        for m in metros:
            state_lookup.setdefault(m.state, {})
            # Index the canonical name
            for key in self._key_variants(m.name):
                global_lookup.setdefault(key, m.id)
                state_lookup[m.state].setdefault(key, m.id)
            # Index aliases
            for alias in m.aliases:
                for key in self._key_variants(alias):
                    global_lookup.setdefault(key, m.id)
                    state_lookup[m.state].setdefault(key, m.id)

        return global_lookup, state_lookup

    def match(
        self, city: str | None, state: str | None = None
    ) -> MatchResult | None:
        """
        Try to match a job posting location to a canonical metro.

        Returns MatchResult or None if no usable match.
        """
        if not city or not city.strip():
            return None

        city_norm = self._normalize(city)
        state_norm = (state or "").strip().upper() or None

        # "remote" / "anywhere" — caller treats this as no-location
        if city_norm in {"remote", "anywhere", "multiple locations", "various"}:
            return None

        # 1. Exact match on full "City, ST"
        if state_norm:
            full_key = f"{city_norm}, {state_norm.lower()}"
            if full_key in self._lookup:
                m = self._by_id[self._lookup[full_key]]
                return MatchResult(metro=m, kind="exact", confidence=1.0)

        # 2. City-only exact in global lookup
        if city_norm in self._lookup:
            m = self._by_id[self._lookup[city_norm]]
            # If a state was given but disagrees, drop the match
            if state_norm and m.state != state_norm:
                pass
            else:
                return MatchResult(metro=m, kind="alias", confidence=0.95)

        # 3. Within-state alias / fuzzy
        if state_norm and state_norm in self._state_lookup:
            state_keys = list(self._state_lookup[state_norm].keys())
            # Try contains-substring match for compound aliases first
            for key in state_keys:
                if city_norm == key or city_norm in key or key in city_norm:
                    metro_id = self._state_lookup[state_norm][key]
                    return MatchResult(metro=self._by_id[metro_id], kind="alias", confidence=0.85)
            # Fuzzy
            best = process.extractOne(
                city_norm,
                state_keys,
                scorer=fuzz.token_sort_ratio,
                score_cutoff=FUZZY_THRESHOLD,
            )
            if best:
                key, score, _ = best
                metro_id = self._state_lookup[state_norm][key]
                return MatchResult(
                    metro=self._by_id[metro_id],
                    kind="fuzzy",
                    confidence=score / 100.0,
                )

        # 4. Global fuzzy (last resort — useful when state is missing/wrong)
        global_keys = list(self._lookup.keys())
        best = process.extractOne(
            city_norm,
            global_keys,
            scorer=fuzz.token_sort_ratio,
            score_cutoff=FUZZY_THRESHOLD,
        )
        if best:
            key, score, _ = best
            metro_id = self._lookup[key]
            return MatchResult(
                metro=self._by_id[metro_id],
                kind="fuzzy",
                confidence=score / 100.0,
            )

        return None

    def _key_variants(self, raw: str) -> set[str]:
        """Yield normalized variants of a name/alias for indexing."""
        base = self._normalize(raw)
        variants = {base}

        # Strip trailing ", ST"
        m = re.match(r"^(.+),\s*([a-z]{2})$", base)
        if m:
            variants.add(m.group(1).strip())
        # Strip punctuation
        no_punct = re.sub(r"[^\w\s,]", "", base).strip()
        if no_punct:
            variants.add(no_punct)
        return variants

    @staticmethod
    def _normalize(s: str) -> str:
        s = s.strip().lower()
        # Collapse whitespace and normalize "St." → "st"
        s = re.sub(r"\bst\.\s", "st ", s)
        s = re.sub(r"\s+", " ", s)
        return s
