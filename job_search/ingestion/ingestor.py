"""Main daily ingestion orchestrator — Subsystem A."""

from __future__ import annotations

import logging
from datetime import datetime

import yaml

from job_search.config import settings
from job_search.db import get_db
from job_search.models import FirmConfig

from .dedup import Deduplicator
from .scoring import Scorer

logger = logging.getLogger(__name__)


class Ingestor:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.scorer = Scorer()
        self._firms: list[FirmConfig] = []

    def load_firms(self, config_path: str = "config/firms.yaml") -> None:
        try:
            with open(config_path) as f:
                raw = yaml.safe_load(f) or {}
            self._firms = [FirmConfig(**firm) for firm in raw.get("firms", [])]
            logger.info("Loaded %d firms from registry", len(self._firms))
        except FileNotFoundError:
            logger.warning("firms.yaml not found — registry empty; only public-sector sources will run")

    def run(self) -> dict:
        stats = {
            "started_at": datetime.utcnow().isoformat(),
            "new": 0,
            "updated": 0,
            "reposts": 0,
            "errors": 0,
            "sources": {},
        }

        with get_db() as db:
            dedup = Deduplicator(db)

            for job in self._iter_all_sources():
                try:
                    job = self.scorer.score(job)
                    if self.dry_run:
                        logger.info("DRY RUN — would upsert: %s @ %s", job.title, job.company)
                        stats["new"] += 1
                        continue
                    is_new, is_repost = dedup.upsert(job)
                    src = stats["sources"].setdefault(job.source, {"new": 0, "updated": 0, "reposts": 0})
                    if is_new:
                        stats["new"] += 1
                        src["new"] += 1
                        self._log_health(db, job.source, job.firm_id, "ok")
                    else:
                        stats["updated"] += 1
                        src["updated"] += 1
                    if is_repost:
                        stats["reposts"] += 1
                        src["reposts"] += 1
                except Exception as exc:
                    logger.error("Failed to process job %s: %s", getattr(job, "source_job_id", "?"), exc)
                    stats["errors"] += 1

        stats["finished_at"] = datetime.utcnow().isoformat()
        logger.info(
            "Ingestion complete: %d new, %d updated, %d reposts, %d errors",
            stats["new"], stats["updated"], stats["reposts"], stats["errors"],
        )
        return stats

    def _iter_all_sources(self):
        """Yield CanonicalJob from all configured sources in priority order."""
        from job_search.adapters import USAJobsAdapter, AdzunaAdapter, GreenhouseAdapter, LeverAdapter, WorkdayAdapter

        # 1. Public sector (USAJOBS)
        yield from self._run_adapter(USAJobsAdapter())

        # 2. Aggregator (Adzuna)
        yield from self._run_adapter(AdzunaAdapter())

        # 3. Green-tier firm adapters
        for firm in self._firms:
            from job_search.models import ATSType, ATSTier
            if firm.ats_tier == ATSTier.GREEN:
                adapter_cls = {
                    ATSType.GREENHOUSE: GreenhouseAdapter,
                    ATSType.LEVER: LeverAdapter,
                }.get(firm.ats_type)
                if adapter_cls:
                    yield from self._run_adapter(adapter_cls(firm))

        # 4. Yellow-tier (Workday) — throttled
        for firm in self._firms:
            from job_search.models import ATSType, ATSTier
            if firm.ats_tier == ATSTier.YELLOW and firm.ats_type == ATSType.WORKDAY:
                yield from self._run_adapter(WorkdayAdapter(firm))

    def _run_adapter(self, adapter):
        source_name = adapter.source_name
        firm_id = getattr(adapter.firm, "firm_id", None) if adapter.firm else None
        try:
            count = 0
            for job in adapter.fetch():
                count += 1
                yield job
            logger.info("Adapter %s/%s: %d jobs yielded", source_name, firm_id or "global", count)
        except Exception as exc:
            logger.error("Adapter %s/%s failed: %s", source_name, firm_id or "global", exc)
            with get_db() as db:
                self._log_health(db, source_name, firm_id, "error", str(exc))

    def _log_health(
        self,
        db,
        source: str,
        firm_id: str | None,
        status: str,
        error_detail: str | None = None,
    ) -> None:
        db.execute(
            """
            INSERT INTO source_health (source, firm_id, status, error_detail)
            VALUES (?, ?, ?, ?)
            """,
            (source, firm_id, status, error_detail),
        )
