"""Keyword extraction and tiering from a job description."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

# Civil engineering keyword taxonomy for tier classification
TIER_1_PATTERNS = [
    # Software (exact match, case-insensitive)
    r"\bautocad\s+civil\s+3d\b", r"\bcivil\s+3d\b", r"\bautocad\b",
    r"\bram\s+structural\b", r"\bram\b", r"\brevit\b", r"\bhec-ras\b",
    r"\bmicrostation\b", r"\bgis\b", r"\barc\s*gis\b",
    r"\bmicrosoft\s+project\b", r"\bms\s+project\b",
    # Credentials
    r"\bengineer\s+in\s+training\b", r"\beit\b", r"\bfe\s+exam\b",
    r"\bprofessional\s+engineer\b", r"\b\bpe\s+license\b",
    # Core civil disciplines
    r"\bstructural\s+(analysis|design|engineering)\b",
    r"\breinforced\s+concrete\b", r"\bsteel\s+design\b",
    r"\bfoundation\s+(design|engineering)\b",
    r"\bsite\s+civil\b", r"\bland\s+development\b",
    r"\btransportation\s+engineering\b", r"\bhydraulic\b", r"\bhydrology\b",
]

TIER_2_PATTERNS = [
    r"\bconstruction\s+management\b", r"\bproject\s+management\b",
    r"\bconstructability\b", r"\bscheduling\b", r"\bcoordination\b",
    r"\bfield\s+engineering\b", r"\bsoil\s+mechanics\b",
    r"\bgeotechnical\b", r"\bsurvey(ing)?\b",
    r"\bdrainage\b", r"\bstormwater\b", r"\bgrading\b",
    r"\bcross-sections?\b", r"\bprofile\b",
    r"\bload\s+analysis\b", r"\blateral\s+(loads?|force)\b",
    r"\bseismic\b", r"\bwind\s+load\b",
]

TIER_3_PATTERNS = [
    r"\bcollaboration\b", r"\bcommunication\b", r"\bteamwork\b",
    r"\battention\s+to\s+detail\b", r"\bproblem.solv\b",
    r"\bms\s+office\b", r"\bmicrosoft\s+office\b",
    r"\btime\s+management\b", r"\borganizational\b",
]


@dataclass
class ExtractedKeyword:
    keyword: str
    tier: int                   # 1=must-have, 2=strong, 3=nice
    frequency: int
    category: str               # software|cert|discipline|skill|other


class KeywordExtractor:
    def extract(self, jd_text: str) -> list[ExtractedKeyword]:
        text = jd_text.lower()
        results: list[ExtractedKeyword] = []
        seen: set[str] = set()

        def _scan(patterns: list[str], tier: int) -> None:
            for pattern in patterns:
                for m in re.finditer(pattern, text, re.IGNORECASE):
                    kw = m.group(0).strip()
                    normalized = re.sub(r"\s+", " ", kw).lower()
                    if normalized not in seen:
                        seen.add(normalized)
                        count = len(re.findall(pattern, text, re.IGNORECASE))
                        results.append(ExtractedKeyword(
                            keyword=kw,
                            tier=tier,
                            frequency=count,
                            category=self._categorize(normalized),
                        ))

        _scan(TIER_1_PATTERNS, 1)
        _scan(TIER_2_PATTERNS, 2)
        _scan(TIER_3_PATTERNS, 3)

        return sorted(results, key=lambda k: (k.tier, -k.frequency))

    def _categorize(self, kw: str) -> str:
        software_hints = ["autocad", "civil 3d", "ram", "revit", "hec-ras", "microstation",
                          "gis", "arcgis", "microsoft project", "ms project"]
        cert_hints = ["eit", "engineer in training", "pe ", "fe exam", "professional engineer"]
        if any(h in kw for h in software_hints):
            return "software"
        if any(h in kw for h in cert_hints):
            return "cert"
        if any(h in kw for h in ["engineering", "design", "analysis", "construction"]):
            return "discipline"
        return "skill"

    def compute_coverage(
        self,
        keywords: list[ExtractedKeyword],
        document_text: str,
    ) -> tuple[float, list[str], list[str]]:
        """Returns (coverage_pct, hit_keywords, missed_keywords) for tier-1+2 only."""
        doc_lower = document_text.lower()
        priority = [k for k in keywords if k.tier <= 2]
        if not priority:
            return 1.0, [], []

        hits, misses = [], []
        for kw in priority:
            if kw.keyword.lower() in doc_lower:
                hits.append(kw.keyword)
            else:
                misses.append(kw.keyword)

        coverage = len(hits) / len(priority) if priority else 1.0
        return round(coverage, 4), hits, misses
