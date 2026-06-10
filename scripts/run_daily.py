#!/usr/bin/env python3
"""
Daily cron entry point — runs on the DigitalOcean droplet.

Crontab example:
  0 7 * * * /path/to/venv/bin/python /path/to/job-search-assistant/scripts/run_daily.py >> /var/log/jsa_daily.log 2>&1
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from job_search.config import settings
from job_search.db import init_db
from job_search.ingestion import Ingestor
from job_search.reporting import DailyReporter, SelectionProcessor
from job_search.tracking import FollowUpEngine

logging.basicConfig(level=settings.LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("run_daily")


def main():
    logger.info("=== Daily job search run starting ===")
    init_db()

    # 1. Ingest fresh postings
    ingestor = Ingestor(dry_run=settings.DRY_RUN)
    ingestor.load_firms()
    logger.info("Ingestion: %s", ingestor.run())

    # 2. Sync James's selections from yesterday's report (Sheet → DB)
    selector = SelectionProcessor()
    logger.info("Sheet sync: %s", selector.sync_from_sheet())

    # 3. Generate docs ONLY for jobs James selected (LLM calls live here)
    gen_stats = selector.generate_for_selected()
    logger.info("Doc generation: generated=%d errors=%d",
                gen_stats["generated"], gen_stats["errors"])

    # 4. Follow-up engine (auto-ghost, surface overdue)
    followup = FollowUpEngine()
    due_actions = followup.run()
    logger.info("Follow-up actions due: %d", len(due_actions))

    # 5. Present new high-fit postings (no LLM)
    reporter = DailyReporter()
    logger.info("Daily report: %s", reporter.run())

    logger.info("=== Daily run complete ===")


if __name__ == "__main__":
    main()
