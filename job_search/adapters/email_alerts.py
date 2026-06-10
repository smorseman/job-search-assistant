"""Email-alert adapter — parses job postings from inbox alert emails.

Legitimate access pattern: reading mail Gmail received from LinkedIn/Indeed
because James opted into their alerts. This is a backstop for the boards
ruled out for direct scraping (see §6.2 of spec).

Once a message is processed, it's tagged with a Processed label so the next
run skips it. Idempotent.
"""

from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass
from email import message_from_bytes
from typing import Iterator

from job_search.config import settings
from job_search.models import ATSType, CanonicalJob, RemoteFlag

from .base import BaseAdapter, AdapterError

logger = logging.getLogger(__name__)

PROCESSED_LABEL_NAME = "jsa-processed"


@dataclass
class RawAlert:
    """An intermediate representation of one job link extracted from an email."""
    title: str
    company: str | None
    location: str | None
    url: str
    snippet: str | None
    sender_domain: str
    message_id: str


class EmailAlertsAdapter(BaseAdapter):
    source_name = "email_alert"

    def __init__(self):
        super().__init__(firm=None)
        self._gmail = None
        self._processed_label_id: str | None = None

    def fetch(self) -> Iterator[CanonicalJob]:
        try:
            self._init_gmail()
        except Exception as exc:
            raise AdapterError(f"Gmail not configured: {exc}") from exc

        for alert in self._iter_unprocessed_alerts():
            try:
                job = self._to_canonical_job(alert)
                if job:
                    yield job
            except Exception as exc:
                logger.error("Failed to parse alert %s: %s", alert.message_id, exc)
            finally:
                # Mark processed even on parse failure to avoid retry storms
                self._mark_processed(alert.message_id)

    # ── Gmail wiring ──────────────────────────────────────────────────────────

    def _init_gmail(self) -> None:
        from job_search.reporting.sheets import SheetsLogger
        from googleapiclient.discovery import build
        creds = SheetsLogger()._get_creds()
        self._gmail = build("gmail", "v1", credentials=creds)
        self._processed_label_id = self._ensure_label(PROCESSED_LABEL_NAME)

    def _ensure_label(self, name: str) -> str:
        labels = self._gmail.users().labels().list(userId="me").execute().get("labels", [])
        for lab in labels:
            if lab["name"].lower() == name.lower():
                return lab["id"]
        # Create it
        created = self._gmail.users().labels().create(
            userId="me",
            body={"name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"},
        ).execute()
        return created["id"]

    def _iter_unprocessed_alerts(self) -> Iterator[RawAlert]:
        alert_label = settings.GMAIL_ALERT_LABEL
        query = f'label:{alert_label} -label:{PROCESSED_LABEL_NAME} newer_than:14d'
        results = self._gmail.users().messages().list(
            userId="me", q=query, maxResults=100
        ).execute()
        messages = results.get("messages", [])
        logger.info("Gmail: %d unprocessed alerts under label '%s'", len(messages), alert_label)

        for ref in messages:
            mid = ref["id"]
            msg = self._gmail.users().messages().get(
                userId="me", id=mid, format="raw"
            ).execute()
            raw_bytes = base64.urlsafe_b64decode(msg["raw"])
            yield from self._parse_message(raw_bytes, mid)

    def _mark_processed(self, message_id: str) -> None:
        try:
            self._gmail.users().messages().modify(
                userId="me",
                id=message_id,
                body={"addLabelIds": [self._processed_label_id]},
            ).execute()
        except Exception as exc:
            logger.warning("Failed to label %s as processed: %s", message_id, exc)

    # ── Message parsing ───────────────────────────────────────────────────────

    def _parse_message(self, raw_bytes: bytes, message_id: str) -> Iterator[RawAlert]:
        msg = message_from_bytes(raw_bytes)
        sender = (msg.get("From") or "").lower()
        sender_domain = self._extract_domain(sender)

        # Concatenate text/plain + text/html bodies
        body_text = ""
        body_html = ""
        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                payload = part.get_payload(decode=True)
                if not payload:
                    continue
                try:
                    decoded = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                except Exception:
                    decoded = payload.decode("utf-8", errors="replace")
                if ctype == "text/plain":
                    body_text += decoded
                elif ctype == "text/html":
                    body_html += decoded
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                body_text = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")

        # Pick the right parser by sender
        if "linkedin.com" in sender_domain:
            yield from self._parse_linkedin(body_html or body_text, message_id, sender_domain)
        elif "indeed.com" in sender_domain or "indeed-mail.com" in sender_domain:
            yield from self._parse_indeed(body_html or body_text, message_id, sender_domain)
        elif "ziprecruiter.com" in sender_domain or "ziprecruiter-mail.com" in sender_domain:
            yield from self._parse_ziprecruiter(body_html or body_text, message_id, sender_domain)
        else:
            yield from self._parse_generic(body_html or body_text, message_id, sender_domain)

    def _extract_domain(self, sender: str) -> str:
        m = re.search(r"@([\w.\-]+)", sender)
        return m.group(1).lower() if m else ""

    # ── Per-sender parsers ────────────────────────────────────────────────────
    # LinkedIn alert HTML pattern: anchor with /jobs/view/{numeric_id}, surrounded
    # by job title + company + location text. We do NOT visit linkedin.com to
    # retrieve more info — only what's already in our inbox.

    def _parse_linkedin(self, body: str, message_id: str, sender_domain: str) -> Iterator[RawAlert]:
        seen_ids: set[str] = set()
        # Anchors to /jobs/view/{id}
        for match in re.finditer(
            r'href="(https?://[^"]*linkedin\.com/comm/jobs/view/(\d+)[^"]*)"[^>]*>([^<]+)</a>',
            body,
            re.IGNORECASE,
        ):
            url, job_id, anchor_text = match.group(1), match.group(2), match.group(3).strip()
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            # The 200 chars after the anchor often contain company + location
            window = body[match.end():match.end() + 600]
            window_text = self._strip_html(window)
            company, location = self._extract_company_location(window_text)
            yield RawAlert(
                title=self._strip_html(anchor_text),
                company=company,
                location=location,
                url=self._canonicalize_linkedin_url(url, job_id),
                snippet=window_text[:300],
                sender_domain=sender_domain,
                message_id=f"linkedin:{job_id}",
            )

    def _canonicalize_linkedin_url(self, url: str, job_id: str) -> str:
        return f"https://www.linkedin.com/jobs/view/{job_id}/"

    def _parse_indeed(self, body: str, message_id: str, sender_domain: str) -> Iterator[RawAlert]:
        seen: set[str] = set()
        for match in re.finditer(
            r'href="(https?://[^"]*indeed\.com/[^"]*(viewjob|rc/clk)[^"]*?jk=([a-f0-9]+)[^"]*)"[^>]*>([^<]+)</a>',
            body,
            re.IGNORECASE,
        ):
            url, _, jk, anchor = match.group(1), match.group(2), match.group(3), match.group(4).strip()
            if jk in seen:
                continue
            seen.add(jk)
            window = body[match.end():match.end() + 600]
            window_text = self._strip_html(window)
            company, location = self._extract_company_location(window_text)
            yield RawAlert(
                title=self._strip_html(anchor),
                company=company,
                location=location,
                url=f"https://www.indeed.com/viewjob?jk={jk}",
                snippet=window_text[:300],
                sender_domain=sender_domain,
                message_id=f"indeed:{jk}",
            )

    def _parse_ziprecruiter(self, body: str, message_id: str, sender_domain: str) -> Iterator[RawAlert]:
        seen: set[str] = set()
        for match in re.finditer(
            r'href="(https?://[^"]*ziprecruiter\.com/[^"]*?/Job/([^/"?]+)[^"]*)"[^>]*>([^<]+)</a>',
            body,
            re.IGNORECASE,
        ):
            url, slug, anchor = match.group(1), match.group(2), match.group(3).strip()
            if slug in seen:
                continue
            seen.add(slug)
            window = body[match.end():match.end() + 600]
            window_text = self._strip_html(window)
            company, location = self._extract_company_location(window_text)
            yield RawAlert(
                title=self._strip_html(anchor),
                company=company,
                location=location,
                url=url,
                snippet=window_text[:300],
                sender_domain=sender_domain,
                message_id=f"ziprecruiter:{slug}",
            )

    def _parse_generic(self, body: str, message_id: str, sender_domain: str) -> Iterator[RawAlert]:
        """Fallback: extract any link that looks like a job posting + nearby text."""
        # Heuristic: any anchor whose URL contains "job", "career", or "posting"
        for match in re.finditer(
            r'href="(https?://[^"]+(?:job|career|posting|opening)[^"]*)"[^>]*>([^<]+)</a>',
            body,
            re.IGNORECASE,
        ):
            url, anchor = match.group(1), match.group(2).strip()
            window = body[max(0, match.start() - 200):match.end() + 400]
            window_text = self._strip_html(window)
            company, location = self._extract_company_location(window_text)
            yield RawAlert(
                title=self._strip_html(anchor),
                company=company,
                location=location,
                url=url,
                snippet=window_text[:300],
                sender_domain=sender_domain,
                message_id=f"email_generic:{hash(url) & 0xFFFFFFFF:x}",
            )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _strip_html(self, html: str) -> str:
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"&nbsp;|&#160;", " ", text)
        text = re.sub(r"&amp;", "&", text)
        text = re.sub(r"&[a-z]+;", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    def _extract_company_location(self, text: str) -> tuple[str | None, str | None]:
        """Best-effort: pull 'Company · City, ST' from the window after the title."""
        # Most alert formats put company and location near the job title
        m = re.search(r"([A-Z][A-Za-z0-9 &.,'-]{2,50})\s*[·•|]\s*([A-Za-z .'-]+,\s*[A-Z]{2})", text)
        if m:
            return m.group(1).strip(), m.group(2).strip()
        # Or just a City, ST without explicit separator
        m = re.search(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*,\s*[A-Z]{2})\b", text)
        location = m.group(1) if m else None
        return None, location

    # ── Normalize to CanonicalJob ─────────────────────────────────────────────

    def _to_canonical_job(self, alert: RawAlert) -> CanonicalJob | None:
        # Skip clearly non-civil titles
        if not self._is_civil_relevant(alert.title, alert.snippet or ""):
            return None
        city, state = self._normalize_location(alert.location)
        return CanonicalJob(
            source=self.source_name,
            source_job_id=alert.message_id,
            company=alert.company or "Unknown (email alert)",
            title=alert.title,
            location_city=city,
            location_state=state,
            remote_flag=RemoteFlag.UNKNOWN,
            description_raw=alert.snippet,
            description_normalized=alert.snippet,
            apply_url=alert.url,
            ats_type=ATSType.OTHER,
        )

    def _is_civil_relevant(self, title: str, snippet: str) -> bool:
        combined = (title + " " + snippet).lower()
        keywords = [
            "civil", "structural", "construction", "geotechnical", "transportation",
            "land development", "site civil", "water resources", "environmental engineer",
            "project engineer", "field engineer", "design engineer", "infrastructure",
            "engineer in training", "eit",
        ]
        return any(kw in combined for kw in keywords)
