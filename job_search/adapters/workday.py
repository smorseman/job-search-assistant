"""Workday adapter — Yellow tier. Per-tenant POST filter; Akamai bot management."""

from __future__ import annotations

import logging
import time
from typing import Iterator

import httpx

from job_search.models import ATSType, CanonicalJob, FirmConfig, KnockoutFields

from .base import BaseAdapter, AdapterError

logger = logging.getLogger(__name__)

# Workday detail endpoint
JOBS_URL = "https://{tenant}.wd{n}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
DETAIL_URL = "https://{tenant}.wd{n}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs/{job_id}"

CIVIL_KEYWORDS = [
    "civil", "structural", "construction", "geotechnical", "transportation",
    "land development", "site civil", "water resources", "environmental engineer",
    "project engineer", "field engineer", "infrastructure",
]

# Workday: throttle between requests to avoid Akamai blocks
REQUEST_DELAY_SECONDS = 3.0
RESULTS_PER_PAGE = 20


class WorkdayAdapter(BaseAdapter):
    source_name = "workday"

    def __init__(self, firm: FirmConfig):
        super().__init__(firm)
        assert firm.ats_tenant, f"Workday firm {firm.firm_id} missing ats_tenant"
        assert firm.ats_site, f"Workday firm {firm.firm_id} missing ats_site"

    def fetch(self) -> Iterator[CanonicalJob]:
        tenant = self.firm.ats_tenant
        site = self.firm.ats_site
        # Try wd1 through wd5 for the right Workday data center
        domain_num = self.firm.default_filters.get("wd_num", 1)
        base = JOBS_URL.format(tenant=tenant, site=site, n=domain_num)

        offset = 0
        while True:
            payload = {
                "appliedFacets": {},
                "limit": RESULTS_PER_PAGE,
                "offset": offset,
                "searchText": "civil engineer",
            }
            try:
                time.sleep(REQUEST_DELAY_SECONDS)
                resp = self._post(base, json=payload)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (403, 429, 503):
                    logger.warning(
                        "Workday %s: anti-bot block (%d) — backing off",
                        self.firm.firm_id, exc.response.status_code,
                    )
                    # Do not escalate evasion — just stop this run
                    return
                raise
            except Exception as exc:
                logger.error("Workday fetch failed for %s: %s", self.firm.firm_id, exc)
                raise

            data = resp.json()
            job_postings = data.get("jobPostings", [])
            total = data.get("total", 0)
            logger.info("Workday %s: offset %d, %d/%d results", self.firm.firm_id, offset, len(job_postings), total)

            if not job_postings:
                break

            for raw in job_postings:
                job = self._normalize(raw, tenant, site, domain_num)
                if job:
                    yield job

            offset += RESULTS_PER_PAGE
            if offset >= min(total, 10000):  # Workday 10k cap
                break

    def _normalize(self, raw: dict, tenant: str, site: str, n: int) -> CanonicalJob | None:
        title = raw.get("title", "")
        if not any(kw in title.lower() for kw in CIVIL_KEYWORDS):
            return None

        ext_id = raw.get("externalPath", "").lstrip("/")
        location = raw.get("locationsText", "") or raw.get("jobPostingLocations", [""])[0] if raw.get("jobPostingLocations") else ""
        city, state = self._normalize_location(location)

        posted = raw.get("postedOnDate") or raw.get("postedDate")

        apply_url = f"https://{tenant}.wd{n}.myworkdayjobs.com/{site}/job/{ext_id}"

        return CanonicalJob(
            source=self.source_name,
            source_job_id=ext_id or raw.get("bulletFields", [""])[0],
            firm_id=self.firm.firm_id,
            company=self.firm.name,
            title=title,
            location_city=city,
            location_state=state,
            apply_url=apply_url,
            posted_date=posted,
            ats_type=ATSType.WORKDAY,
        )
