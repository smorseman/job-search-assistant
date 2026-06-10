"""Validate that the master profile has all required fields populated."""

from __future__ import annotations

from pathlib import Path

import yaml

REQUIRED_PATHS: list[tuple[str, ...]] = [
    ("identity", "first_name"),
    ("identity", "last_name"),
    ("identity", "email"),
    ("identity", "phone"),
    ("identity", "location", "city"),
    ("identity", "location", "state"),
    ("eligibility", "work_authorization"),
    ("education",),
    ("software",),
]


def validate_profile_content(path: Path) -> tuple[bool, list[str]]:
    """Return (ok, list_of_issues)."""
    with open(path) as f:
        data = yaml.safe_load(f) or {}

    issues: list[str] = []
    for keypath in REQUIRED_PATHS:
        value = data
        path_str = ".".join(keypath)
        try:
            for key in keypath:
                value = value[key]
        except (KeyError, TypeError):
            issues.append(f"missing: {path_str}")
            continue

        if value in ("", None) or (isinstance(value, list) and not value):
            issues.append(f"empty: {path_str}")

    # Spot check: at least one experience or project
    exp_count = len(data.get("experience") or [])
    proj_count = len(data.get("projects") or [])
    if exp_count == 0 and proj_count == 0:
        issues.append("no experience or projects provided")

    return len(issues) == 0, issues
