# Job Search Assistant

Automated civil-engineering job pipeline for James.

Finds, scores, and tailors applications for civil engineering roles daily.
James reviews and submits — the system never submits on his behalf.

## Architecture

```
Subsystem A (daily cron)                    Subsystem B (weekly)
  USAJOBS API  ──┐                            ENR / ACEC seeds ──┐
  Adzuna API   ──┤                            ATS fingerprinting ─┤
  Greenhouse   ──┤ → dedup → score → DB       Registry config    ──┘
  Lever        ──┤
  Workday      ──┘
        │
        ▼
  Document generation (Claude API)
        │
        ▼
  Daily report (Drive) + Google Sheets mirror
        │
        ▼
  James reviews → selects → submits
        │
        ▼
  State machine → follow-up engine → funnel stats
```

## Quick start

```bash
# 1. Secrets — fill in API keys; never committed
cp .env.example .env

# 2. Profile — fill in James's real data; never committed
cp profile/james_profile.example.yaml profile/james_profile.yaml

# 3. Run
jsa init-db
jsa ingest --dry-run    # verify sources work
jsa ingest              # real run
jsa report              # generate today's report
jsa stats               # funnel stats
```

## Privacy

This repo may be public, but **no real personal data is committed**:
- `.env` (API keys) — gitignored
- `profile/james_profile.yaml` (real PII) — gitignored
- `credentials.json` / `token.json` (Google OAuth) — gitignored

The committed `*.example.yaml` files are templates with placeholders only.

## Build sequence (§18)

- [x] 1. Master profile schema (`profile/james_profile.yaml`)
- [x] 2. Canonical schema + SQLite + Greenhouse adapter (vertical slice)
- [x] 3. USAJOBS + Adzuna adapters; dedup + repost detection
- [x] 4. Document generation + keyword tiering; daily report
- [x] 5. Google Sheets logging + Drive snapshots + follow-up engine
- [x] 6. Employer discovery pipeline + registry; remaining Green adapters
- [x] 7. Workday (Yellow) adapter with throttling; self-healing / circuit breaker
- [ ] 8. Email-alert parser (Gmail); Lever/Ashby/SmartRecruiters adapters; funnel stats email

## See also

- `DEPLOY.md` — DigitalOcean setup + cron configuration
- `profile/james_profile.yaml` — candidate fact base (fill in before first run)
- `config/firms.yaml` — employer registry (config-as-code)
- `config/scoring.yaml` — scoring weight overrides
