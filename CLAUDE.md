# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Does

Automated civil-engineering job pipeline for a candidate named James. It ingests job postings from 11 sources daily, scores them deterministically, and defers expensive LLM calls (resume/cover-letter generation) until James explicitly flags a job to apply for via a Google Sheet. LLM is used only for two narrowly scoped tasks: fit-grading (Anthropic Message Batches API, −50% cost) and document generation (two Claude API calls per selected job).

**Core philosophy**: deterministic Python everywhere; LLM as a scalpel, not an agent in the hot path.

## Commands

```bash
# Install (editable, dev deps)
pip install -e ".[dev]"

# CLI entry point (all user-facing commands)
jsa <command>

# Lint
ruff check job_search tests

# Tests
pytest -q --tb=short
DRY_RUN=true pytest     # safe for CI; adapters skip writes

# Type check (not enforced in CI, but available)
mypy
```

Key `jsa` commands:
```bash
jsa init-db                          # ensure schema + idempotent migrations
jsa preflight                        # validate keys, profile, DB connectivity
jsa ingest [--dry-run]               # fetch all sources, dedup, score
jsa grade [--timeout S] [--max-jobs N] [--dry-run]  # LLM fit-grading batch
jsa sync-sheet                       # read James's Sheet edits → DB state transitions
jsa generate [job_ids] [--force]     # generate resume+cover for SELECTED jobs
jsa report                           # surface top-N postings to Sheet
jsa stats                            # funnel breakdown
jsa discover-firm <name> <url>       # fingerprint a new employer into firms.yaml
jsa followup                         # surface overdue follow-up actions
```

## Architecture

### Two-Phase Pipeline

**Phase 1 — Daily ingestion** (`scripts/run_daily.py`, triggered by cron at 7 AM):
```
Ingestor → Deduplicator → Scorer → DB
  └─ 11 adapters yield CanonicalJob records
  └─ jd_content_hash (MD5 of normalized description) detects reposts
  └─ match_score = weighted sum(discipline + location + benefit + trajectory)

FitGrader (after ingest)
  └─ Queries DISCOVERED jobs with match_score ≥ GRADING_FLOOR (default 0.55)
  └─ Submits to Anthropic Message Batches API (grade-once, never re-grade)
  └─ Stores llm_grade, llm_fit_score, llm_rationale in DB

DailyReporter
  └─ Surfaces top-N jobs (match_score ≥ PRESENTATION_THRESHOLD) to Google Sheet
```

**Phase 2 — Selection & generation** (James acts on Sheet; `jsa sync-sheet` + `jsa generate`):
```
James edits "status" column in Sheet
  └─ "apply" / "selected" → SELECTED state → queue for document generation
  └─ "applied"            → APPLIED state → start 14-day follow-up clock
  └─ "skip" / "rejected"  → REJECTED state (terminal)

DocumentGenerator (for SELECTED jobs, two Claude calls per job)
  └─ KeywordExtractor extracts priority keywords from JD
  └─ Resume generation (tailored from master profile + keywords, prompt-cached)
  └─ Cover letter generation
  └─ Uploads .docx to Google Drive, writes URL back to Sheet
```

### Key Modules

| Path | Role |
|------|------|
| `job_search/cli.py` | All 15 Click commands; single user-facing entry point |
| `job_search/models.py` | `CanonicalJob` (44-field dataclass), `FirmConfig`, all enums (`AppState`, `ATSTier`, `ATSType`, `RemoteFlag`) |
| `job_search/db/schema.sql` | 8-table SQLite schema (firms, jobs, app_transitions, generated_docs, job_keywords, daily_reports, grading_batches, source_health, followup_queue) |
| `job_search/ingestion/ingestor.py` | Orchestrates all adapters; source dispatch order |
| `job_search/ingestion/scoring.py` | Match formula; reads weights from `config/scoring.yaml` |
| `job_search/adapters/base.py` | Abstract adapter interface; tenacity HTTP retry logic; `AdapterError` exception |
| `job_search/adapters/` | 11 concrete ATS adapters (Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee, Workday, Adzuna, USAJOBS, email alerts) |
| `job_search/grading/grader.py` | Message Batches API submission + polling; grade-once guard |
| `job_search/generation/generator.py` | Resume + cover-letter generation via Claude; prompt caching for profile |
| `job_search/reporting/selection.py` | Sheet → DB state sync; triggers doc generation on "apply" |
| `job_search/tracking/state_machine.py` | `VALID_TRANSITIONS` dict; enforces legal state transitions |
| `job_search/healing/circuit_breaker.py` | Per-source health tracking; quarantines anti-bot sources (never evades) |
| `job_search/location/scorer.py` | 50-metro framework; 5 scoring dimensions × 5 schemes; `CityMatcher` fuzzy lookup |

### Config-as-Code

| File | Purpose |
|------|---------|
| `config/firms.yaml` | Employer registry: ATS fingerprints, tier, board tokens, benefits, ENR rank. Circuit-breaker heals commit diffs here for audit trail. |
| `config/scoring.yaml` | Match-score weights (discipline weights, formula coefficients, thresholds). Edit here to tune ranking. |
| `config/cities.yaml` | 50-metro framework: 5-dimensional city scores used by `LocationScorer`. |
| `profile/james_profile.yaml` | Master profile — **gitignored**. `profile/james_profile.example.yaml` is the template. |

### Application State Machine

```
DISCOVERED → PRESENTED → SELECTED → APPLIED → INTERVIEWING → OFFER → ACCEPTED
                                   ↓
                                REJECTED (terminal, reachable from most states)
                                   ↓
                                WITHDRAWN (terminal)
```

State transitions are enforced by `VALID_TRANSITIONS` in `job_search/tracking/state_machine.py`. All transitions are logged to `app_transitions` table.

## Environment Variables

See `.env.example` for the full list. Key ones:

| Variable | Purpose |
|----------|---------|
| `ANTHROPIC_API_KEY` | Required for grading and document generation |
| `PROFILE_PATH` | Path to `james_profile.yaml` (gitignored) |
| `DB_PATH` | SQLite file (default: `data/jobs.db`) |
| `TRACKER_SHEET_ID` | Google Sheet used for job review and status tracking |
| `DRIVE_ROOT_FOLDER_ID` | Google Drive folder for generated .docx files |
| `GMAIL_ALERT_LABEL` | Gmail label routing job-alert emails to the adapter |
| `DRY_RUN` | Set `true` to fetch but skip all DB writes (used in tests/CI) |
| `GRADING_MAX_JOBS` | Cost guardrail; default 50 jobs per grading run |
| `GRADING_FLOOR` | Minimum match_score to grade; default 0.55 |

## Testing Conventions

- HTTP calls are mocked with `respx` — never make live network calls in tests.
- Anthropic client is mocked with a `FakeBatches` class (see `tests/test_grading.py`).
- DB tests use a tmp SQLite file via pytest fixtures; never touch `data/jobs.db`.
- `asyncio_mode = "auto"` is set in `pyproject.toml`; async test functions work without decorators.
- Run a single test: `pytest tests/test_grading.py -q --tb=short`

## Hard Constraints

- **No auto-apply**: The system must never submit an application autonomously. James always decides.
- **No config auto-rewrite**: `config/firms.yaml` changes should be committed as diffs for audit.
- **No anti-bot evasion**: If a source returns an anti-bot block, quarantine it. Never retry with IP rotation or header spoofing.
- **LLM only on selection**: Document generation runs only when James sets status to "apply". Never generate docs eagerly on ingestion.
- **Grade-once**: `llm_grade` is written once. Re-grading requires `--force` explicitly. Guard this in any grading code changes.
