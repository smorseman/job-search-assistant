"""Ashby adapter — Green tier, public posting API."""

from __future__ import annotations

import logging
from collections.abc import Iterator

from job_search.models import ATSType, CanonicalJob, FirmConfig, RemoteFlag

from .base import BaseAdapter
from .greenhouse import CIVIL_KEYWORDS

logger = logging.getLogger(__name__)

BASE_URL = "https://api.ashbyhq.com/posting-api/job-board/{token}"


class AshbyAdapter(BaseAdapter):
    source_name = "ashby"

    def __init__(self, firm: FirmConfig):
        super().__init__(firm)
        assert firm.ats_board_token, f"Ashby firm {firm.firm_id} missing board_token"

    def fetch(self) -> Iterator[CanonicalJob]:
        token = self.firm.ats_board_token
        try:
            resp = self._get(
                BASE_URL.format(token=token),
                params={"includeCompensation": "true"},
            )
        except Exception as exc:
            logger.error("Ashby fetch failed for %s: %s", self.firm.firm_id, exc)
            raise

        data = resp.json()
        postings = data.get("jobs", [])
        logger.info("Ashby %s: %d postings", self.firm.firm_id, len(postings))

        for raw in postings:
            job = self._normalize(raw)
            if job:
                yield job

    def _normalize(self, raw: dict) -> CanonicalJob | None:
        title = raw.get("title", "")
        description = raw.get("descriptionPlain") or raw.get("descriptionHtml") or ""
        if not self._is_civil_relevant(title, description):
            return None

        location = raw.get("locationName") or raw.get("location") or ""
        city, state = self._normalize_location(location)
        is_remote = raw.get("isRemote", False)

        return CanonicalJob(
            source=self.source_name,
            source_job_id=raw["id"],
            firm_id=self.firm.firm_id,
            company=self.firm.name,
            title=title,
            location_city=city,
            location_state=state,
            remote_flag=RemoteFlag.YES if is_remote else (RemoteFlag.NO if location else RemoteFlag.UNKNOWN),
            description_raw=description,
            description_normalized=self._strip_html(description),
            apply_url=raw.get("jobUrl") or raw.get("applyUrl"),
            posted_date=raw.get("publishedAt", "")[:10] if raw.get("publishedAt") else None,
            ats_type=ATSType.ASHBY,
        )

    def _is_civil_relevant(self, title: str, content: str) -> bool:
        combined = (title + " " + content).lower()
        return any(kw in combined for kw in CIVIL_KEYWORDS)

    def _strip_html(self, html: str) -> str:
        import re
        text = re.sub(r"<[^>]+>", " ", html)
        return re.sub(r"\s+", " ", text).strip()
