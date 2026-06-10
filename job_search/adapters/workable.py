"""Workable adapter — Green tier, public widget API.

Workable's public-facing endpoint is the widget JSON:
  https://apply.workable.com/api/v3/accounts/{subdomain}/jobs?state=published

No auth required for published postings.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

from job_search.models import ATSType, CanonicalJob, FirmConfig, RemoteFlag

from .base import BaseAdapter
from .greenhouse import CIVIL_KEYWORDS

logger = logging.getLogger(__name__)

LIST_URL = "https://apply.workable.com/api/v3/accounts/{subdomain}/jobs"


class WorkableAdapter(BaseAdapter):
    source_name = "workable"

    def __init__(self, firm: FirmConfig):
        super().__init__(firm)
        assert firm.ats_board_token, f"Workable firm {firm.firm_id} missing board_token (subdomain)"

    def fetch(self) -> Iterator[CanonicalJob]:
        subdomain = self.firm.ats_board_token
        page = 1
        while True:
            params = {"state": "published", "limit": 100, "page": page}
            try:
                resp = self._get(LIST_URL.format(subdomain=subdomain), params=params)
            except Exception as exc:
                logger.error("Workable fetch failed for %s: %s", self.firm.firm_id, exc)
                raise

            data = resp.json()
            results = data.get("results", [])
            logger.info("Workable %s page %d: %d results", self.firm.firm_id, page, len(results))

            if not results:
                break

            for raw in results:
                job = self._normalize(raw, subdomain)
                if job:
                    yield job

            # Workable paginates with a nextPage URL or page count
            if len(results) < 100:
                break
            page += 1

    def _normalize(self, raw: dict, subdomain: str) -> CanonicalJob | None:
        title = raw.get("title", "")
        if not self._is_civil_relevant(title, raw.get("description", "")):
            return None

        loc = raw.get("location", {}) or {}
        city = loc.get("city")
        state = loc.get("region")
        is_remote = raw.get("remote", False) or loc.get("workplaceType") == "remote"

        shortcode = raw.get("shortcode") or raw.get("id")
        apply_url = f"https://apply.workable.com/{subdomain}/j/{shortcode}/" if shortcode else None

        return CanonicalJob(
            source=self.source_name,
            source_job_id=str(shortcode),
            firm_id=self.firm.firm_id,
            company=self.firm.name,
            title=title,
            location_city=city,
            location_state=state,
            remote_flag=RemoteFlag.YES if is_remote else RemoteFlag.NO,
            description_raw=raw.get("description"),
            description_normalized=self._strip_html(raw.get("description", "")),
            apply_url=apply_url,
            posted_date=(raw.get("published") or "")[:10] if raw.get("published") else None,
            ats_type=ATSType.WORKABLE,
        )

    def _is_civil_relevant(self, title: str, content: str) -> bool:
        combined = (title + " " + content).lower()
        return any(kw in combined for kw in CIVIL_KEYWORDS)

    def _strip_html(self, html: str) -> str:
        import re
        text = re.sub(r"<[^>]+>", " ", html or "")
        return re.sub(r"\s+", " ", text).strip()
