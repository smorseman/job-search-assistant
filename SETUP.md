# Setup Checklist

Run through this once before the first `jsa ingest`. Order matters in a couple of places.

## 1. Local install

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
jsa init-db
```

## 2. API keys

Copy the template, then fill in each row below.

```bash
cp .env.example .env
```

### Required for first useful run

| Key | Cost | Where to get it | What it powers |
|---|---|---|---|
| `USAJOBS_API_KEY` | Free | https://developer.usajobs.gov/apirequest/ (instant approval) | Federal civil engineering postings (Army Corps, Reclamation, FHWA, etc.) |
| `USAJOBS_EMAIL` | — | Your email | USAJOBS requires it in the `User-Agent` header |
| `ANTHROPIC_API_KEY` | Pay-as-you-go (~$30–60/mo at full volume) | https://console.anthropic.com/ → API Keys | Resume + cover letter generation |

### Required for full pipeline

| Key | Cost | Where to get it | What it powers |
|---|---|---|---|
| `ADZUNA_APP_ID` + `ADZUNA_API_KEY` | Free tier (1000 calls/mo) | https://developer.adzuna.com/ | Aggregator postings — broad civil coverage |
| `GOOGLE_CREDENTIALS_PATH` | Free | Google Cloud Console → APIs & Services → Credentials → OAuth 2.0 Client ID → Desktop app | Sheets + Drive + Gmail OAuth |
| `TRACKER_SHEET_ID` | Free | Create a blank Google Sheet, copy ID from URL (`/d/{ID}/edit`) | Application tracker mirror |
| `DRIVE_ROOT_FOLDER_ID` | Free | Create a Drive folder, copy ID from URL | Per-application resume/cover snapshots |
| `GMAIL_ALERT_LABEL` | — | Default `job-alerts`; create the label in Gmail and route LinkedIn/Indeed alerts to it | Email-alert ingestion |

### Optional now / important later

| Key | Why |
|---|---|
| Static IP allowlist on droplet | If Workday's anti-bot starts flagging you, rotating IPs would be evasion (against policy). Keep the same IP and back off. |
| Sentry DSN | If you want error notifications without logging into the droplet daily |

## 3. Google OAuth — first-time consent

Browser-based; run once locally (NOT on the headless droplet):

```bash
python -c "from job_search.reporting.sheets import SheetsLogger; SheetsLogger()._get_creds()"
```

This opens a browser, you grant Sheets+Drive+Gmail, and `token.json` is written. **Copy that `token.json` to the droplet** — it auto-refreshes from there.

## 4. Profile data

```bash
cp profile/james_profile.example.yaml profile/james_profile.yaml
nano profile/james_profile.yaml
```

Every `# FILL IN` must be resolved. Don't commit this file — `.gitignore` already protects it.

## 5. Preflight check

```bash
jsa preflight
```

This validates every key is set and every required file exists. Green across the board = safe to run `jsa ingest`.

## 6. Seed the employer registry

Pick a starting list (ENR Top 500, ACEC directory, target firms). For each:

```bash
jsa discover-firm "Kimley-Horn" https://kimley-horn.com
jsa discover-firm "Walter P Moore" https://walterpmoore.com
jsa discover-firm "Thornton Tomasetti" https://thorntontomasetti.com
# ... add 15–30 to start
```

Each writes to `config/firms.yaml`; commit periodically so the registry is versioned.

## 7. First run

```bash
jsa ingest --dry-run     # verify sources answer; no DB writes
jsa ingest               # real run
jsa report               # generate today's documents + report
jsa stats                # confirm jobs landed
```

## 8. Cron (after several manual runs succeed)

See `DEPLOY.md` §6.
