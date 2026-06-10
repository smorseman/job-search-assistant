"""Adzuna adapter — free-tier API, broad aggregator coverage."""

from __future__ import annotations

import logging
from typing import Iterator

from job_search.config import settings
from job_search.models import ATSType, CanonicalJob, KnockoutFields, RemoteFlag

from .base import BaseAdapter, AdapterError

logger = logging.getLogger(__name__)

BASE_URL = "https://api.adzuna.com/v1/api/jobs/us/search/{page}"

SEARCH_QUERIES = [
    "civil engineer",
    "structural engineer",
    "construction engineer",
    "project engineer civil",
    "land development engineer",
    "transportation engineer",
    "geotechnical engineer",
    "water resources engineer",
]

MAX_PAGES_PER_QUERY = 5
RESULTS_PER_PAGE = 50


class AdzunaAdapter(BaseAdapter):
    source_name = "adzuna"

    def fetch(self) -> Iterator[CanonicalJob]:
        if not settings.ADZUNA_APP_ID or not settings.ADZUNA_API_KEY:
            raise AdapterError("ADZUNA_APP_ID / ADZUNA_API_KEY not configured")

        for query in SEARCH_QUERIES:
            yield from self._fetch_query(query)

    def _fetch_query(self, query: str) -> Iterator[CanonicalJob]:
        for page in range(1, MAX_PAGES_PER_QUERY + 1):
            params = {
                "app_id": settings.ADZUNA_APP_ID,
                "app_key": settings.ADZUNA_API_KEY,
                "results_per_page": RESULTS_PER_PAGE,
                "what": query,
                "category": "engineering-jobs",
                "content-type": "application/json",
            }
            try:
                resp = self._get(BASE_URL.format(page=page), params=params)
            except Exception as exc:
                logger.error("Adzuna fetch failed query='%s' page=%d: %s", query, page, exc)
                return

            data = resp.json()
            results = data.get("results", [])
            total = data.get("count", 0)
            logger.info("Adzuna '%s' page %d: %d/%d results", query, page, len(results), total)

            if not results:
                return

            for raw in results:
                job = self._normalize(raw)
                if job:
                    yield job

            if page * RESULTS_PER_PAGE >= total:
                return

    def _normalize(self, raw: dict) -> CanonicalJob | None:
        job_id = str(raw.get("id", ""))
        title = raw.get("title", "")
        company = raw.get("company", {}).get("display_name", "Unknown")
        description = raw.get("description", "")

        location = raw.get("location", {})
        display_loc = location.get("display_name", "")
        area = location.get("area", [])
        city = area[-1] if area else None
        state = area[-2] if len(area) >= 2 else None

        salary_min = int(raw["salary_min"]) if raw.get("salary_min") else None
        salary_max = int(raw["salary_max"]) if raw.get("salary_max") else None

        return CanonicalJob(
            source=self.source_name,
            source_job_id=job_id,
            company=company,
            title=title,
            location_city=city,
            location_state=state,
            description_raw=description,
            description_normalized=description,
            apply_url=raw.get("redirect_url"),
            posted_date=self._parse_date(raw.get("created")),
            salary_min=salary_min,
            salary_max=salary_max,
            ats_type=ATSType.OTHER,
        )

    def _parse_date(self, raw: str | None) -> str | None:
        if not raw:
            return None
        return raw[:10]
