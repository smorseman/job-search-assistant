"""Preflight: check that everything needed for a real run is in place.

Run via `jsa preflight`. Returns a structured report; never raises.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from job_search.config import settings


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    severity: str = "required"   # "required" | "recommended" | "optional"


@dataclass
class PreflightReport:
    checks: list[Check] = field(default_factory=list)

    @property
    def all_required_ok(self) -> bool:
        return all(c.ok for c in self.checks if c.severity == "required")

    @property
    def summary(self) -> dict[str, int]:
        return {
            "required_ok": sum(1 for c in self.checks if c.severity == "required" and c.ok),
            "required_total": sum(1 for c in self.checks if c.severity == "required"),
            "recommended_ok": sum(1 for c in self.checks if c.severity == "recommended" and c.ok),
            "recommended_total": sum(1 for c in self.checks if c.severity == "recommended"),
        }


def run_preflight() -> PreflightReport:
    report = PreflightReport()

    # ── API keys ──────────────────────────────────────────────────────────────
    report.checks.append(_check_key("USAJOBS_API_KEY", "required", "Federal civil-eng postings; free instant approval"))
    report.checks.append(_check_key("USAJOBS_EMAIL", "required", "Required in USAJOBS User-Agent header"))
    report.checks.append(_check_key("ANTHROPIC_API_KEY", "required", "Resume/cover-letter generation + fit-grading"))
    report.checks.append(_check_key("ADZUNA_APP_ID", "recommended", "Broad aggregator; free tier"))
    report.checks.append(_check_key("ADZUNA_API_KEY", "recommended", "Broad aggregator; free tier"))

    # ── Google integration ────────────────────────────────────────────────────
    cred_path = settings.GOOGLE_CREDENTIALS_PATH
    cred_ok = Path(cred_path).exists()
    report.checks.append(Check(
        name="google_credentials.json",
        ok=cred_ok,
        detail=f"{cred_path} {'present' if cred_ok else 'NOT FOUND — download OAuth2 desktop credentials from GCP'}",
        severity="recommended",
    ))
    token_ok = Path(settings.GOOGLE_TOKEN_PATH).exists()
    report.checks.append(Check(
        name="google_token.json",
        ok=token_ok,
        detail=f"{settings.GOOGLE_TOKEN_PATH} {'present' if token_ok else 'NOT FOUND — run first-time OAuth flow locally'}",
        severity="recommended",
    ))
    report.checks.append(_check_key("TRACKER_SHEET_ID", "recommended", "Application tracker Sheet ID"))
    report.checks.append(_check_key("DRIVE_ROOT_FOLDER_ID", "recommended", "Parent Drive folder for snapshots"))

    # ── Profile + config files ────────────────────────────────────────────────
    profile_path = Path(settings.PROFILE_PATH)
    profile_exists = profile_path.exists()
    report.checks.append(Check(
        name="profile/james_profile.yaml",
        ok=profile_exists,
        detail=(
            f"{profile_path} present"
            if profile_exists
            else f"Run: cp {settings.PROFILE_TEMPLATE_PATH} {profile_path}, then fill in"
        ),
        severity="required",
    ))

    cities = Path("config/cities.yaml").exists()
    report.checks.append(Check(
        name="config/cities.yaml",
        ok=cities,
        detail="50-metro location framework",
        severity="required",
    ))

    firms = Path("config/firms.yaml").exists()
    report.checks.append(Check(
        name="config/firms.yaml",
        ok=firms,
        detail="Employer registry — empty registry means USAJOBS+Adzuna only",
        severity="recommended",
    ))

    # ── DB ────────────────────────────────────────────────────────────────────
    db_path = Path(settings.DB_PATH)
    db_ok = db_path.exists()
    report.checks.append(Check(
        name=f"DB ({db_path})",
        ok=db_ok,
        detail="Run: jsa init-db" if not db_ok else "initialized",
        severity="required",
    ))

    # ── LLM fit-grading (informational) ───────────────────────────────────────
    report.checks.append(Check(
        name="LLM fit-grading",
        ok=True,
        detail=(
            f"enabled (floor={settings.GRADING_FLOOR}, max/run={settings.GRADING_MAX_JOBS}, "
            f"timeout={settings.GRADING_POLL_TIMEOUT_S}s)"
            if settings.GRADING_ENABLED else "disabled"
        ),
        severity="optional",
    ))

    # ── Profile content validation ────────────────────────────────────────────
    if profile_exists:
        from job_search.profile_check import validate_profile_content
        ok, issues = validate_profile_content(profile_path)
        report.checks.append(Check(
            name="profile content",
            ok=ok,
            detail=("all required fields populated" if ok else "; ".join(issues[:5])),
            severity="required",
        ))

    return report


def _check_key(env_name: str, severity: str, detail: str) -> Check:
    """Check that an env var is set to something other than the placeholder."""
    value = getattr(settings, env_name, "") or ""
    is_placeholder = (
        not value
        or value.startswith("your_")
        or value == "your_email@example.com"
    )
    return Check(
        name=env_name,
        ok=not is_placeholder,
        detail=detail if not is_placeholder else f"NOT SET — {detail}",
        severity=severity,
    )
