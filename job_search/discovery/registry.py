"""Employer discovery — Subsystem B.

Seeded enumeration approach: start from known lists, fingerprint ATS,
classify tier, validate, persist as config-as-code in firms.yaml.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx
import yaml

from job_search.models import ATSTier, ATSType, FirmConfig

logger = logging.getLogger(__name__)

# ATS fingerprint patterns: URL/script patterns → (ats_type, tier)
ATS_FINGERPRINTS: list[tuple[re.Pattern, ATSType, ATSTier]] = [
    (re.compile(r"boards\.greenhouse\.io/([a-zA-Z0-9_-]+)", re.I), ATSType.GREENHOUSE, ATSTier.GREEN),
    (re.compile(r"jobs\.lever\.co/([a-zA-Z0-9_-]+)", re.I), ATSType.LEVER, ATSTier.GREEN),
    (re.compile(r"jobs\.ashbyhq\.com/([a-zA-Z0-9_-]+)", re.I), ATSType.ASHBY, ATSTier.GREEN),
    (re.compile(r"jobs\.smartrecruiters\.com/([a-zA-Z0-9_-]+)", re.I), ATSType.SMARTRECRUITERS, ATSTier.GREEN),
    (re.compile(r"([a-zA-Z0-9_-]+)\.recruitee\.com", re.I), ATSType.RECRUITEE, ATSTier.GREEN),
    (re.compile(r"([a-zA-Z0-9_-]+)\.workable\.com", re.I), ATSType.WORKABLE, ATSTier.GREEN),
    (re.compile(r"([a-zA-Z0-9_-]+)\.myworkdayjobs\.com", re.I), ATSType.WORKDAY, ATSTier.YELLOW),
    (re.compile(r"([a-zA-Z0-9_-]+)\.icims\.com", re.I), ATSType.ICIMS, ATSTier.RED),
    (re.compile(r"taleo\.net|oracle.*taleo", re.I), ATSType.TALEO, ATSTier.RED),
    (re.compile(r"successfactors", re.I), ATSType.SUCCESSFACTORS, ATSTier.RED),
]

CAREERS_PATH_HINTS = ["/careers", "/jobs", "/join", "/work-with-us", "/opportunities"]


class RegistryBuilder:
    def __init__(self, config_path: str = "config/firms.yaml"):
        self.config_path = config_path
        self.http = httpx.Client(timeout=15, follow_redirects=True)

    def fingerprint_firm(self, name: str, website: str) -> FirmConfig | None:
        """
        Resolve careers URL, fingerprint ATS, classify tier.
        Returns a FirmConfig ready to persist, or None if discovery fails.
        """
        careers_url = self._find_careers_url(website)
        if not careers_url:
            logger.info("No careers URL found for %s (%s)", name, website)
            return None

        ats_type, ats_tier, board_token, tenant, site = self._fingerprint(careers_url)

        firm_id = self._make_slug(name)
        config = FirmConfig(
            firm_id=firm_id,
            name=name,
            website=website,
            careers_url=careers_url,
            ats_type=ats_type,
            ats_tier=ats_tier,
            ats_board_token=board_token,
            ats_tenant=tenant,
            ats_site=site,
        )
        logger.info(
            "Fingerprinted %s: %s / %s (token=%s tenant=%s)",
            name, ats_type.value, ats_tier.value, board_token, tenant,
        )
        return config

    def validate(self, config: FirmConfig) -> bool:
        """Live test query to confirm the config returns results."""
        if config.ats_tier == ATSTier.RED:
            return False  # Never probe Red tier
        try:
            if config.ats_type == ATSType.GREENHOUSE and config.ats_board_token:
                resp = self.http.get(
                    f"https://boards-api.greenhouse.io/v1/boards/{config.ats_board_token}/jobs"
                )
                return resp.status_code == 200 and len(resp.json().get("jobs", [])) > 0
            if config.ats_type == ATSType.LEVER and config.ats_board_token:
                resp = self.http.get(f"https://api.lever.co/v0/postings/{config.ats_board_token}")
                return resp.status_code == 200
        except Exception as exc:
            logger.debug("Validation failed for %s: %s", config.firm_id, exc)
        return False

    def upsert_to_config(self, config: FirmConfig) -> None:
        """Persist or update a firm config record in firms.yaml (config-as-code)."""
        try:
            with open(self.config_path) as f:
                data = yaml.safe_load(f) or {}
        except FileNotFoundError:
            data = {}

        firms = data.get("firms", [])
        existing_idx = next((i for i, f in enumerate(firms) if f.get("firm_id") == config.firm_id), None)
        record = config.model_dump(exclude_none=True)

        if existing_idx is not None:
            old = firms[existing_idx]
            firms[existing_idx] = record
            logger.info("Updated firm config: %s", config.firm_id)
            self._log_config_change(config.firm_id, old, record)
        else:
            firms.append(record)
            logger.info("Added new firm to registry: %s", config.firm_id)

        data["firms"] = firms
        with open(self.config_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def _find_careers_url(self, website: str) -> str | None:
        """Try common careers URL patterns before fetching and scanning."""
        base = website.rstrip("/")
        for path in CAREERS_PATH_HINTS:
            url = base + path
            try:
                resp = self.http.head(url)
                if resp.status_code < 400:
                    return url
            except Exception:
                continue

        # Fall back to fetching homepage and looking for careers links
        try:
            resp = self.http.get(website)
            links = re.findall(r'href=["\'](.*?)["\']', resp.text, re.I)
            for link in links:
                if any(hint.lstrip("/") in link.lower() for hint in CAREERS_PATH_HINTS):
                    if link.startswith("http"):
                        return link
                    return base + "/" + link.lstrip("/")
        except Exception:
            pass
        return None

    def _fingerprint(
        self, careers_url: str
    ) -> tuple[ATSType, ATSTier, str | None, str | None, str | None]:
        """Detect ATS type from the careers page URL and content."""
        # First try URL patterns
        for pattern, ats_type, tier in ATS_FINGERPRINTS:
            m = pattern.search(careers_url)
            if m:
                token_or_slug = m.group(1) if m.lastindex else None
                if ats_type in (ATSType.GREENHOUSE, ATSType.LEVER, ATSType.ASHBY,
                                ATSType.SMARTRECRUITERS, ATSType.WORKABLE, ATSType.RECRUITEE):
                    return ats_type, tier, token_or_slug, None, None
                if ats_type == ATSType.WORKDAY:
                    # tenant is group(1); site often the same or "External"
                    tenant = m.group(1)
                    return ats_type, tier, None, tenant, "External"

        # Scan page content for embedded ATS script patterns
        try:
            resp = self.http.get(careers_url, timeout=10)
            content = resp.text
            for pattern, ats_type, tier in ATS_FINGERPRINTS:
                m = pattern.search(content)
                if m:
                    token = m.group(1) if m.lastindex else None
                    return ats_type, tier, token, None, None
        except Exception:
            pass

        return ATSType.UNKNOWN, ATSTier.UNKNOWN, None, None, None

    def _make_slug(self, name: str) -> str:
        slug = name.lower()
        slug = re.sub(r"[^a-z0-9]+", "_", slug)
        return slug.strip("_")[:40]

    def _log_config_change(self, firm_id: str, old: dict, new: dict) -> None:
        """Each heal that changes config should ideally be a git commit (manual for now)."""
        logger.info("Config change for %s: %s → %s", firm_id, old.get("ats_type"), new.get("ats_type"))
