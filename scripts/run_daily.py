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
from job_search.reporting import DailyReporter
from job_search.tracking import FollowUpEngine

logging.basicConfig(level=settings.LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("run_daily")


def main():
    logger.info("=== Daily job search run starting ===")

    # Ensure DB schema is up to date
    init_db()

    # 1. Ingest
    ingestor = Ingestor(dry_run=settings.DRY_RUN)
    ingestor.load_firms()
    ingest_stats = ingestor.run()
    logger.info("Ingestion: %s", ingest_stats)

    # 2. Follow-up engine (flag ghosted, surface overdue)
    followup = FollowUpEngine()
    due_actions = followup.run()
    logger.info("Follow-up actions due: %d", len(due_actions))

    # 3. Generate documents + daily report
    reporter = DailyReporter()
    report_stats = reporter.run()
    logger.info("Report: %s", report_stats)

    logger.info("=== Daily run complete ===")


if __name__ == "__main__":
    main()
