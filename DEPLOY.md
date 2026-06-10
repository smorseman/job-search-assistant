# Deployment Guide — DigitalOcean Droplet

## 1. Droplet setup

```bash
# On the droplet (Ubuntu 22.04 or 24.04 recommended)
sudo apt update && sudo apt install -y python3.12 python3.12-venv git

git clone git@github.com:YOUR_GITHUB_USER/job-search-assistant.git
cd job-search-assistant

python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## 2. Secrets

```bash
cp .env.example .env
# Fill in every key — NEVER commit .env
nano .env
```

### API keys to obtain

| Key | Where to get |
|-----|-------------|
| `USAJOBS_API_KEY` | https://developer.usajobs.gov/apirequest/ (free, instant) |
| `ADZUNA_APP_ID/KEY` | https://developer.adzuna.com/ (free tier) |
| `ANTHROPIC_API_KEY` | https://console.anthropic.com/ |
| Google OAuth2 | Google Cloud Console → OAuth2 desktop credentials → download `credentials.json` |

### Google OAuth2 first-time auth

Run once locally (opens browser for consent):
```bash
python -c "from job_search.reporting.sheets import SheetsLogger; SheetsLogger()._get_creds()"
```
Copy the generated `token.json` to the droplet. Token auto-refreshes from there.

## 3. Initialize DB

```bash
jsa init-db
```

## 4. Populate the employer registry

```bash
# Fingerprint firms one by one
jsa discover-firm "Kimley-Horn" https://kimley-horn.com
jsa discover-firm "Walter P Moore" https://walterpmoore.com

# Or populate config/firms.yaml directly and run scripts/run_discovery.py
python scripts/run_discovery.py
```

## 5. Fill in James's profile

```bash
cp profile/james_profile.example.yaml profile/james_profile.yaml
nano profile/james_profile.yaml
```

Resolve every `# FILL IN` comment before the first run.
The real `profile/james_profile.yaml` is gitignored — never commit it.

## 6. Cron jobs

```bash
crontab -e
```

Add:
```cron
# Daily ingestion + report (7 AM server time)
0 7 * * * /path/to/.venv/bin/python /path/to/job-search-assistant/scripts/run_daily.py >> /var/log/jsa_daily.log 2>&1

# Weekly employer discovery (Sunday 9 AM)
0 9 * * 0 /path/to/.venv/bin/python /path/to/job-search-assistant/scripts/run_discovery.py >> /var/log/jsa_discovery.log 2>&1
```

## 7. Monitoring

```bash
# Manual run with verbose output
LOG_LEVEL=DEBUG jsa ingest --dry-run

# Check funnel stats
jsa stats

# Surface today's follow-up actions
jsa followup
```

## 8. Updating

```bash
cd job-search-assistant
git pull
pip install -e .
jsa init-db   # safe to re-run; schema uses CREATE IF NOT EXISTS
```

## 9. Secrets management reminder

- `.env` is in `.gitignore` — verify with `git status` before every push.
- `credentials.json` and `token*.json` are in `.gitignore`.
- Rotate keys if either file is ever accidentally committed.
