"""Abstract base adapter — every source implements this interface."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Iterator

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from job_search.models import CanonicalJob, FirmConfig

logger = logging.getLogger(__name__)

# Shared HTTP client — one per process, reused across adapters
_http_client: httpx.Client | None = None


def get_http_client() -> httpx.Client:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.Client(
            timeout=30.0,
            headers={"User-Agent": "JobSearchAssistant/0.1 (legitimate job search tool)"},
            follow_redirects=True,
        )
    return _http_client


class AdapterError(Exception):
    """Raised when an adapter encounters an unrecoverable error for this run."""


class BaseAdapter(ABC):
    """
    One adapter per ATS type.  Each firm is a FirmConfig data record.
    Adding a firm = one config record.  Adding an ATS = one new subclass here.
    """

    source_name: str = ""   # override in subclass: "greenhouse", "usajobs", etc.

    def __init__(self, firm: FirmConfig | None = None):
        self.firm = firm
        self.http = get_http_client()

    @abstractmethod
    def fetch(self) -> Iterator[CanonicalJob]:
        """Yield normalized CanonicalJob records.  Must be idempotent."""

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.HTTPStatusError)),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def _get(self, url: str, **kwargs) -> httpx.Response:
        resp = self.http.get(url, **kwargs)
        if resp.status_code == 429:
            raise httpx.HTTPStatusError("Rate limited", request=resp.request, response=resp)
        resp.raise_for_status()
        return resp

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.HTTPStatusError)),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def _post(self, url: str, **kwargs) -> httpx.Response:
        resp = self.http.post(url, **kwargs)
        if resp.status_code == 429:
            raise httpx.HTTPStatusError("Rate limited", request=resp.request, response=resp)
        resp.raise_for_status()
        return resp

    def _normalize_location(self, raw: str | None) -> tuple[str | None, str | None]:
        """Best-effort parse of 'City, ST' → (city, state)."""
        if not raw:
            return None, None
        parts = [p.strip() for p in raw.split(",")]
        if len(parts) >= 2:
            return parts[0], parts[1].split()[0]  # drop extra tokens
        return raw.strip(), None
