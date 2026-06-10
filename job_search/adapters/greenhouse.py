"""Greenhouse adapter — Green tier, no auth required."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterator

from job_search.models import ATSType, CanonicalJob, FirmConfig, KnockoutFields, RemoteFlag

from .base import BaseAdapter

logger = logging.getLogger(__name__)

BASE_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
DETAIL_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{job_id}"

CIVIL_KEYWORDS = [
    "civil", "structural", "construction", "geotechnical", "transportation",
    "land development", "site civil", "water resources", "environmental engineer",
    "project engineer", "field engineer", "design engineer", "infrastructure",
]


class GreenhouseAdapter(BaseAdapter):
    source_name = "greenhouse"

    def __init__(self, firm: FirmConfig):
        super().__init__(firm)
        assert firm.ats_board_token, f"Greenhouse firm {firm.firm_id} missing board_token"

    def fetch(self) -> Iterator[CanonicalJob]:
        token = self.firm.ats_board_token
        try:
            resp = self._get(BASE_URL.format(token=token), params={"content": "true"})
        except Exception as exc:
            logger.error("Greenhouse fetch failed for %s: %s", self.firm.firm_id, exc)
            raise

        data = resp.json()
        jobs = data.get("jobs", [])
        logger.info("Greenhouse %s: %d postings", self.firm.firm_id, len(jobs))

        for raw in jobs:
            job = self._normalize(raw, token)
            if job:
                yield job

    def _normalize(self, raw: dict, token: str) -> CanonicalJob | None:
        title = raw.get("title", "")
        if not self._is_civil_relevant(title, raw.get("content", "")):
            return None

        location = raw.get("location", {}).get("name", "")
        city, state = self._normalize_location(location)

        posted = raw.get("updated_at") or raw.get("created_at")
        posted_date = self._parse_date(posted)

        content = raw.get("content", "") or ""

        return CanonicalJob(
            source=self.source_name,
            source_job_id=str(raw["id"]),
            firm_id=self.firm.firm_id,
            company=self.firm.name,
            title=title,
            location_city=city,
            location_state=state,
            remote_flag=self._detect_remote(title, content, location),
            description_raw=content,
            description_normalized=self._normalize_text(content),
            apply_url=raw.get("absolute_url"),
            posted_date=posted_date,
            ats_type=ATSType.GREENHOUSE,
        )

    def _is_civil_relevant(self, title: str, content: str) -> bool:
        combined = (title + " " + content).lower()
        return any(kw in combined for kw in CIVIL_KEYWORDS)

    def _detect_remote(self, title: str, content: str, location: str) -> RemoteFlag:
        combined = (title + " " + content + " " + location).lower()
        if "remote" in combined:
            return RemoteFlag.YES
        if "hybrid" in combined:
            return RemoteFlag.HYBRID
        if location and location.lower() not in ("remote", ""):
            return RemoteFlag.NO
        return RemoteFlag.UNKNOWN

    def _parse_date(self, raw: str | None) -> str | None:
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            return None

    def _normalize_text(self, html: str) -> str:
        """Strip HTML tags for a clean text representation."""
        import re
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text)
        return text.strip()
