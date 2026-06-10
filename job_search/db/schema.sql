-- ─────────────────────────────────────────────────────────────────────────────
-- Job Search Assistant — SQLite schema
-- SQLite is the canonical source of truth; Google Sheet is a human-facing mirror.
-- ─────────────────────────────────────────────────────────────────────────────

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ── Employer registry ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS firms (
    firm_id          TEXT PRIMARY KEY,           -- slug: "aecom", "jacobs", etc.
    name             TEXT NOT NULL,
    website          TEXT,
    careers_url      TEXT,
    ats_type         TEXT,                       -- greenhouse|lever|workday|smartrecruiters|ashby|workable|icims|taleo|other|unknown
    ats_board_token  TEXT,                       -- Greenhouse board token or Lever company slug
    ats_tenant       TEXT,                       -- Workday tenant
    ats_site         TEXT,                       -- Workday site
    ats_tier         TEXT DEFAULT 'unknown',     -- green|yellow|red|unknown
    enr_rank         INTEGER,                    -- ENR Top 500 rank if known
    employee_count   TEXT,                       -- rough band: "1-50","51-200","201-1000","1001+"
    specialties      TEXT,                       -- JSON array of discipline tags
    known_benefits   TEXT,                       -- JSON array of benefit keys
    tuition_reimbursement INTEGER DEFAULT 0,     -- boolean
    pe_support        INTEGER DEFAULT 0,
    near_grad_programs TEXT,                     -- JSON array of nearby university names
    reputation_notes TEXT,
    circuit_state    TEXT DEFAULT 'closed',      -- closed|open (circuit breaker)
    quarantine_until TEXT,                       -- ISO datetime, null if not quarantined
    consecutive_failures INTEGER DEFAULT 0,
    last_successful_fetch TEXT,                  -- ISO datetime
    last_fingerprinted TEXT,                     -- ISO datetime
    created_at       TEXT DEFAULT (datetime('now')),
    updated_at       TEXT DEFAULT (datetime('now'))
);

-- ── Canonical jobs ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS jobs (
    canonical_job_id    TEXT PRIMARY KEY,        -- SHA256(source + ":" + source_job_id)
    source              TEXT NOT NULL,           -- usajobs|adzuna|greenhouse|lever|workday|email_alert|...
    source_job_id       TEXT NOT NULL,
    firm_id             TEXT REFERENCES firms(firm_id),
    company             TEXT NOT NULL,
    title               TEXT NOT NULL,
    discipline_tags     TEXT,                    -- JSON array
    location_city       TEXT,
    location_state      TEXT,
    location_country    TEXT DEFAULT 'US',
    remote_flag         TEXT DEFAULT 'unknown',  -- yes|no|hybrid|unknown
    description_raw     TEXT,
    description_normalized TEXT,
    jd_content_hash     TEXT,                    -- for repost detection
    apply_url           TEXT,
    posted_date         TEXT,                    -- ISO date
    first_seen          TEXT DEFAULT (datetime('now')),
    last_seen           TEXT DEFAULT (datetime('now')),
    salary_min          INTEGER,
    salary_max          INTEGER,
    -- Parsed knockout fields
    ko_work_auth        TEXT,                    -- requirement string, null if not stated
    ko_min_years        REAL,
    ko_eit_required     INTEGER,                 -- 0|1|null
    ko_pe_required      INTEGER,
    ko_clearance        TEXT,
    ko_relocation       TEXT,
    ko_degree_required  TEXT,                    -- e.g. "BS Civil Engineering"
    -- Scoring
    match_score         REAL,
    stretch_category    TEXT,                    -- qualified|competitive_stretch|long_shot
    benefit_score       REAL DEFAULT 0.0,
    career_trajectory_score REAL DEFAULT 0.0,
    -- Application state
    app_state           TEXT DEFAULT 'discovered', -- see state machine
    -- Metadata
    ats_type            TEXT,
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now')),
    UNIQUE(source, source_job_id)
);

CREATE INDEX IF NOT EXISTS idx_jobs_state     ON jobs(app_state);
CREATE INDEX IF NOT EXISTS idx_jobs_score     ON jobs(match_score DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_firm      ON jobs(firm_id);
CREATE INDEX IF NOT EXISTS idx_jobs_posted    ON jobs(posted_date DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_hash      ON jobs(jd_content_hash);

-- ── Application state transitions ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS app_transitions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_job_id TEXT NOT NULL REFERENCES jobs(canonical_job_id),
    from_state      TEXT,
    to_state        TEXT NOT NULL,
    transitioned_at TEXT DEFAULT (datetime('now')),
    note            TEXT
);

-- ── Generated documents ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS generated_docs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_job_id TEXT NOT NULL REFERENCES jobs(canonical_job_id),
    doc_type         TEXT NOT NULL,              -- resume|cover_letter
    drive_file_id    TEXT,                       -- immutable snapshot in Drive
    drive_url        TEXT,
    keyword_coverage REAL,                       -- % of JD top-tier keywords hit
    keywords_hit     TEXT,                       -- JSON array
    keywords_missed  TEXT,                       -- JSON array
    model_used       TEXT,
    generated_at     TEXT DEFAULT (datetime('now'))
);

-- ── Keyword extraction per job ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS job_keywords (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_job_id TEXT NOT NULL REFERENCES jobs(canonical_job_id),
    keyword          TEXT NOT NULL,
    priority_tier    INTEGER,                    -- 1=must-have, 2=strong, 3=nice
    frequency        INTEGER DEFAULT 1,
    category         TEXT                        -- software|cert|discipline|skill|other
);

-- ── Daily reports ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS daily_reports (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    report_date     TEXT NOT NULL,               -- ISO date
    job_ids         TEXT,                        -- JSON array of canonical_job_ids
    drive_file_id   TEXT,
    email_message_id TEXT,
    generated_at    TEXT DEFAULT (datetime('now'))
);

-- ── Source health log ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS source_health (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT NOT NULL,
    firm_id         TEXT,
    run_at          TEXT DEFAULT (datetime('now')),
    status          TEXT NOT NULL,               -- ok|empty|error|quarantined
    records_fetched INTEGER DEFAULT 0,
    error_class     TEXT,                        -- transient|silent_drift|endpoint_moved|anti_bot|persistent
    error_detail    TEXT,
    heal_action     TEXT,
    old_config      TEXT,                        -- JSON snapshot before heal
    new_config      TEXT                         -- JSON snapshot after heal
);

-- ── Follow-up queue ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS followup_queue (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_job_id TEXT NOT NULL REFERENCES jobs(canonical_job_id),
    action_type      TEXT NOT NULL,              -- check_status|send_followup|update_state
    due_date         TEXT NOT NULL,              -- ISO date
    resolved         INTEGER DEFAULT 0,
    resolved_at      TEXT,
    note             TEXT,
    created_at       TEXT DEFAULT (datetime('now'))
);

-- ── Triggers: keep updated_at fresh ──────────────────────────────────────────
CREATE TRIGGER IF NOT EXISTS jobs_updated_at
    AFTER UPDATE ON jobs
BEGIN
    UPDATE jobs SET updated_at = datetime('now') WHERE canonical_job_id = NEW.canonical_job_id;
END;

CREATE TRIGGER IF NOT EXISTS firms_updated_at
    AFTER UPDATE ON firms
BEGIN
    UPDATE firms SET updated_at = datetime('now') WHERE firm_id = NEW.firm_id;
END;
