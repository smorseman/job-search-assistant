"""Lever adapter — Green tier, no auth required."""

from __future__ import annotations

import logging
from collections.abc import Iterator

from job_search.models import ATSType, CanonicalJob, FirmConfig, RemoteFlag

from .base import BaseAdapter
from .greenhouse import CIVIL_KEYWORDS

logger = logging.getLogger(__name__)

BASE_URL = "https://api.lever.co/v0/postings/{company}"


class LeverAdapter(BaseAdapter):
    source_name = "lever"

    def __init__(self, firm: FirmConfig):
        super().__init__(firm)
        assert firm.ats_board_token, f"Lever firm {firm.firm_id} missing board_token (company slug)"

    def fetch(self) -> Iterator[CanonicalJob]:
        slug = self.firm.ats_board_token
        try:
            resp = self._get(
                BASE_URL.format(company=slug),
                params={"mode": "json"},
            )
        except Exception as exc:
            logger.error("Lever fetch failed for %s: %s", self.firm.firm_id, exc)
            raise

        jobs = resp.json()
        logger.info("Lever %s: %d postings", self.firm.firm_id, len(jobs))

        for raw in jobs:
            job = self._normalize(raw)
            if job:
                yield job

    def _normalize(self, raw: dict) -> CanonicalJob | None:
        title = raw.get("text", "")
        categories = raw.get("categories", {})
        team = categories.get("team", "")
        department = categories.get("department", "")
        description = (raw.get("descriptionBody") or raw.get("description") or "")

        if not self._is_civil_relevant(title, description, team, department):
            return None

        location = categories.get("location", "")
        city, state = self._normalize_location(location)

        return CanonicalJob(
            source=self.source_name,
            source_job_id=raw["id"],
            firm_id=self.firm.firm_id,
            company=self.firm.name,
            title=title,
            location_city=city,
            location_state=state,
            remote_flag=self._detect_remote(title, description, location),
            description_raw=description,
            description_normalized=self._normalize_text(description),
            apply_url=raw.get("hostedUrl"),
            ats_type=ATSType.LEVER,
        )

    def _is_civil_relevant(self, *texts: str) -> bool:
        combined = " ".join(texts).lower()
        return any(kw in combined for kw in CIVIL_KEYWORDS)

    def _detect_remote(self, title: str, content: str, location: str) -> RemoteFlag:
        combined = (title + " " + content + " " + location).lower()
        if "remote" in combined:
            return RemoteFlag.YES
        if "hybrid" in combined:
            return RemoteFlag.HYBRID
        if location:
            return RemoteFlag.NO
        return RemoteFlag.UNKNOWN

    def _normalize_text(self, html: str) -> str:
        import re
        text = re.sub(r"<[^>]+>", " ", html)
        return re.sub(r"\s+", " ", text).strip()
