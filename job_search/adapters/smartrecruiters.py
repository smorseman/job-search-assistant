"""SmartRecruiters adapter — Green tier, public posting API."""

from __future__ import annotations

import logging
from collections.abc import Iterator

from job_search.models import ATSType, CanonicalJob, FirmConfig

from .base import BaseAdapter
from .greenhouse import CIVIL_KEYWORDS

logger = logging.getLogger(__name__)

LIST_URL = "https://api.smartrecruiters.com/v1/companies/{company}/postings"
PAGE_LIMIT = 100


class SmartRecruitersAdapter(BaseAdapter):
    source_name = "smartrecruiters"

    def __init__(self, firm: FirmConfig):
        super().__init__(firm)
        assert firm.ats_board_token, f"SmartRecruiters firm {firm.firm_id} missing board_token (company slug)"

    def fetch(self) -> Iterator[CanonicalJob]:
        company = self.firm.ats_board_token
        offset = 0
        total = None

        while True:
            params = {"limit": PAGE_LIMIT, "offset": offset}
            try:
                resp = self._get(LIST_URL.format(company=company), params=params)
            except Exception as exc:
                logger.error("SmartRecruiters fetch failed for %s: %s", self.firm.firm_id, exc)
                raise

            data = resp.json()
            content = data.get("content", [])
            total = data.get("totalFound", total)
            logger.info(
                "SmartRecruiters %s: offset %d, %d results (total %s)",
                self.firm.firm_id, offset, len(content), total,
            )

            if not content:
                break

            for raw in content:
                job = self._normalize(raw)
                if job:
                    yield job

            offset += PAGE_LIMIT
            if total is not None and offset >= total:
                break

    def _normalize(self, raw: dict) -> CanonicalJob | None:
        title = raw.get("name", "")
        if not self._is_civil_relevant(title, ""):
            # Need to fetch detail for description — skip non-titled civils
            # to avoid an N+1 burst. We'll trust the title for civil filter.
            return None

        loc = raw.get("location", {}) or {}
        city = loc.get("city")
        state = loc.get("region")
        country = (loc.get("country") or "us").upper()

        return CanonicalJob(
            source=self.source_name,
            source_job_id=raw["id"],
            firm_id=self.firm.firm_id,
            company=self.firm.name,
            title=title,
            location_city=city,
            location_state=state,
            location_country=country,
            apply_url=(raw.get("ref") or "") + "" if raw.get("ref") else self._build_apply_url(raw),
            posted_date=self._extract_date(raw.get("releasedDate")),
            ats_type=ATSType.SMARTRECRUITERS,
        )

    def _build_apply_url(self, raw: dict) -> str | None:
        # SmartRecruiters posting page: /{company}/{posting_id}
        company = self.firm.ats_board_token
        pid = raw.get("id")
        if company and pid:
            return f"https://jobs.smartrecruiters.com/{company}/{pid}"
        return None

    def _is_civil_relevant(self, title: str, content: str) -> bool:
        combined = (title + " " + content).lower()
        return any(kw in combined for kw in CIVIL_KEYWORDS)

    def _extract_date(self, raw_date: str | None) -> str | None:
        if not raw_date:
            return None
        return raw_date[:10]
