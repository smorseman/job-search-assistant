"""USAJOBS adapter — official REST API, federal civil engineering roles."""

from __future__ import annotations

import logging
from typing import Iterator

from job_search.config import settings
from job_search.models import ATSType, CanonicalJob, KnockoutFields, RemoteFlag

from .base import BaseAdapter, AdapterError

logger = logging.getLogger(__name__)

SEARCH_URL = "https://data.usajobs.gov/api/search"

# Occupation series relevant to civil/structural engineering
CIVIL_SERIES = ["0810", "0819", "0830", "0840", "0850", "0896", "1176"]

KEYWORDS = [
    "civil engineer", "structural engineer", "construction engineer",
    "project engineer", "transportation engineer", "geotechnical engineer",
    "water resources engineer", "environmental engineer",
    "land development", "site civil",
]


class USAJobsAdapter(BaseAdapter):
    source_name = "usajobs"

    def fetch(self) -> Iterator[CanonicalJob]:
        if not settings.USAJOBS_API_KEY:
            raise AdapterError("USAJOBS_API_KEY not configured")

        headers = {
            "Authorization-Key": settings.USAJOBS_API_KEY,
            "User-Agent": settings.USAJOBS_EMAIL or "job-search-assistant@example.com",
            "Host": "data.usajobs.gov",
        }

        for keyword in KEYWORDS:
            yield from self._fetch_keyword(keyword, headers)

    def _fetch_keyword(self, keyword: str, headers: dict) -> Iterator[CanonicalJob]:
        page = 1
        while True:
            params = {
                "Keyword": keyword,
                "ResultsPerPage": 50,
                "Page": page,
                "Fields": "Min",
            }
            try:
                resp = self._get(SEARCH_URL, headers=headers, params=params)
            except Exception as exc:
                logger.error("USAJOBS fetch failed for keyword '%s': %s", keyword, exc)
                return

            data = resp.json()
            search_result = data.get("SearchResult", {})
            items = search_result.get("SearchResultItems", [])
            count = int(search_result.get("SearchResultCountAll", 0))

            logger.info("USAJOBS '%s' page %d: %d/%d results", keyword, page, len(items), count)

            for item in items:
                job = self._normalize(item)
                if job:
                    yield job

            if page * 50 >= min(count, 1000):  # USAJOBS caps at 1000
                break
            page += 1

    def _normalize(self, item: dict) -> CanonicalJob | None:
        mv = item.get("MatchedObjectDescriptor", {})
        title = mv.get("PositionTitle", "")
        job_id = mv.get("PositionID", "")
        if not job_id:
            return None

        location_list = mv.get("PositionLocation", [{}])
        location = location_list[0] if location_list else {}
        city = location.get("CityName")
        state = location.get("CountrySubDivisionCode")

        salary_range = mv.get("PositionRemuneration", [{}])[0] if mv.get("PositionRemuneration") else {}
        sal_min = self._parse_salary(salary_range.get("MinimumRange"))
        sal_max = self._parse_salary(salary_range.get("MaximumRange"))

        description = mv.get("QualificationSummary", "")
        user_area = item.get("MatchedObjectDetail", {})
        if user_area:
            description += " " + str(user_area)

        # Parse basic knockouts from the structured data
        ko = KnockoutFields()
        ko.work_auth = "US Citizen or Permanent Resident (federal)"
        qualifications = mv.get("QualificationSummary", "").lower()
        if "professional engineer" in qualifications or " pe " in qualifications:
            ko.pe_required = True
        if "engineer in training" in qualifications or " eit " in qualifications or "fe exam" in qualifications:
            ko.eit_required = True

        return CanonicalJob(
            source=self.source_name,
            source_job_id=job_id,
            company=mv.get("OrganizationName", "Federal Government"),
            title=title,
            location_city=city,
            location_state=state,
            description_raw=description,
            description_normalized=description,
            apply_url=mv.get("ApplyURI", [None])[0],
            posted_date=self._parse_date(mv.get("PublicationStartDate")),
            salary_min=sal_min,
            salary_max=sal_max,
            knockout=ko,
            ats_type=ATSType.USAJOBS,
        )

    def _parse_salary(self, val: str | None) -> int | None:
        if not val:
            return None
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return None

    def _parse_date(self, raw: str | None) -> str | None:
        if not raw:
            return None
        return raw[:10]  # ISO date prefix
