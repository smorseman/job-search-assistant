#!/usr/bin/env python3
"""
Employer discovery — periodic run (weekly/monthly).
Seeds from a list of firm names+URLs, fingerprints ATS, adds to registry.

Crontab example:
  0 9 * * 0 /path/to/venv/bin/python /path/to/job-search-assistant/scripts/run_discovery.py >> /var/log/jsa_discovery.log 2>&1
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from job_search.discovery import RegistryBuilder

logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("run_discovery")

# Seed list — add firm names + websites here; discovery handles the rest.
# Pull from ENR Top 500, ACEC directories, or reverse-discovery from ingested postings.
SEED_FIRMS: list[tuple[str, str]] = [
    # ("AECOM", "https://aecom.com"),
    # ("Jacobs", "https://jacobs.com"),
    # ("WSP", "https://wsp.com"),
    # ("Kimley-Horn", "https://kimley-horn.com"),
    # ("Thornton Tomasetti", "https://thorntontomasetti.com"),
    # ("Walter P Moore", "https://walterpmoore.com"),
    # ("Magnusson Klemencic Associates", "https://mka.com"),
    # ("Degenkolb Engineers", "https://degenkolb.com"),
    # Add more from ENR Top 500 / ACEC directories
]


def main():
    builder = RegistryBuilder()
    added = 0
    for name, website in SEED_FIRMS:
        logger.info("Fingerprinting: %s (%s)", name, website)
        config = builder.fingerprint_firm(name, website)
        if config:
            valid = builder.validate(config)
            if valid or config.ats_tier.value in ("yellow",):  # yellow: add even if not validated (ATS requires full search)
                builder.upsert_to_config(config)
                added += 1
                logger.info("Added: %s (%s / %s)", name, config.ats_type.value, config.ats_tier.value)
            else:
                logger.info("Skipped (not validated): %s", name)
    logger.info("Discovery complete: %d firms added/updated", added)


if __name__ == "__main__":
    main()
