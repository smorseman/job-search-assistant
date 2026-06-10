"""Recruitee adapter — Green tier, public offers API.

Public endpoint per tenant subdomain:
  https://{subdomain}.recruitee.com/api/offers/
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

from job_search.models import ATSType, CanonicalJob, FirmConfig, RemoteFlag

from .base import BaseAdapter
from .greenhouse import CIVIL_KEYWORDS

logger = logging.getLogger(__name__)

LIST_URL = "https://{subdomain}.recruitee.com/api/offers/"


class RecruiteeAdapter(BaseAdapter):
    source_name = "recruitee"

    def __init__(self, firm: FirmConfig):
        super().__init__(firm)
        assert firm.ats_board_token, f"Recruitee firm {firm.firm_id} missing board_token (subdomain)"

    def fetch(self) -> Iterator[CanonicalJob]:
        subdomain = self.firm.ats_board_token
        try:
            resp = self._get(LIST_URL.format(subdomain=subdomain))
        except Exception as exc:
            logger.error("Recruitee fetch failed for %s: %s", self.firm.firm_id, exc)
            raise

        data = resp.json()
        offers = data.get("offers", [])
        logger.info("Recruitee %s: %d offers", self.firm.firm_id, len(offers))

        for raw in offers:
            job = self._normalize(raw)
            if job:
                yield job

    def _normalize(self, raw: dict) -> CanonicalJob | None:
        title = raw.get("title", "")
        description = raw.get("description") or ""
        if not self._is_civil_relevant(title, description):
            return None

        city = raw.get("city")
        state = raw.get("state_code") or raw.get("country_code")
        is_remote = raw.get("remote") or raw.get("on_site") is False

        return CanonicalJob(
            source=self.source_name,
            source_job_id=str(raw["id"]),
            firm_id=self.firm.firm_id,
            company=self.firm.name,
            title=title,
            location_city=city,
            location_state=state,
            remote_flag=RemoteFlag.YES if is_remote else (RemoteFlag.NO if city else RemoteFlag.UNKNOWN),
            description_raw=description,
            description_normalized=self._strip_html(description),
            apply_url=raw.get("careers_url") or raw.get("url"),
            posted_date=(raw.get("published_at") or "")[:10] if raw.get("published_at") else None,
            ats_type=ATSType.RECRUITEE,
        )

    def _is_civil_relevant(self, title: str, content: str) -> bool:
        combined = (title + " " + content).lower()
        return any(kw in combined for kw in CIVIL_KEYWORDS)

    def _strip_html(self, html: str) -> str:
        import re
        text = re.sub(r"<[^>]+>", " ", html or "")
        return re.sub(r"\s+", " ", text).strip()
