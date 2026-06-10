#!/usr/bin/env python3
"""One-time DB setup."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from job_search.db import init_db
init_db()
print("DB initialized.")
