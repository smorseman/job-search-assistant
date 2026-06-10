# Architecture — LLM scope + Agentic extensions

## Current architecture (v0.1): deterministic pipeline, LLM as a focused tool

The daily pipeline is **plain Python with two narrowly-scoped LLM calls** per
high-fit posting. Nothing else in the system invokes a model.

```
cron @ 7 AM
   └─ scripts/run_daily.py
       ├─ Ingestor           ← HTTP fetches, schema normalization, dedup (Python)
       ├─ Scorer             ← discipline + location + benefit + trajectory (Python)
       ├─ FollowUpEngine     ← state machine math (Python)
       └─ DailyReporter
           ├─ for each top-scored job:
           │   ├─ Claude API → resume.json    ← LLM call #1
           │   └─ Claude API → cover.json     ← LLM call #2
           └─ Upload to Drive, update Sheet (Python)
```

### Why this shape (vs. agent-driven end-to-end)

| Requirement | Why deterministic wins |
|---|---|
| Hard no-fabrication rule | LLM only sees the profile as ground-truth JSON. Strictly bounded — can't invent jobs, scores, employers. |
| Self-healing must never become self-evasion | Failure modes are explicit (circuit breaker classes). Agentic flow can fail in surprising ways. |
| Cost | ~30 LLM calls/day × ~$0.06 ≈ ~$60/month with caching. Agentic flow could be 10–50× that. |
| Auditability | Every score reproducible from DB. Agentic decisions are harder to re-derive. |
| Reliability | A cron that must finish in <10 min should be deterministic. |
| Testability | 46+ tests today; agentic flow is much harder to assert on. |

The mantra: **LLM as scalpel at the document-generation step, deterministic
Python everywhere else.**

---

## Agentic extensions — opt-in next steps

These are bounded, sidecar tools that *augment* the deterministic pipeline
without entering its hot path. Each can be built independently when there's
a clear payoff signal.

### A. `jsa suggest-firms` — reverse-discovery agent

**Trigger**: weekly or on-demand.
**Input**: recent ingested postings, current `config/firms.yaml`.
**Action**: agent identifies company names appearing in postings that aren't
yet in the registry, ranks them by frequency × civil-discipline density, and
proposes additions for `jsa discover-firm` to fingerprint.
**Output**: a candidate-firms TSV; James/Steve approves; CLI runs the
fingerprint pass.
**Why agentic**: company-name normalization is messy (acronyms, subsidiaries,
parent vs child orgs) and benefits from judgment.
**Boundary**: agent never edits `firms.yaml` directly — it only suggests.

### B. `jsa tune-weights` — funnel-analysis agent

**Trigger**: after ≥30 applications submitted (enough signal).
**Input**: funnel stats by source, discipline, scheme, location, knockout
flags. Conversion rates per stage.
**Action**: agent looks at where applications die — too-narrow discipline
filter, location scheme miscalibration, sources with 0% response, scoring
thresholds too tight — and proposes diffs to `config/scoring.yaml`.
**Output**: a YAML patch + reasoning, presented to Steve as a PR-style review.
**Why agentic**: weight-tuning is a small space but the reasoning over funnel
data is qualitative.
**Boundary**: produces a diff; never auto-applies. Steve reviews + merges.

### C. `jsa parse-jd` — fallback JD knockout extractor

**Trigger**: when the regex knockout parser returns no fields for a posting
above the generation threshold (currently 0.55 match_score).
**Input**: full JD text.
**Action**: agent extracts work-auth, min years, EIT/PE requirement,
clearance, degree requirement as structured JSON.
**Output**: structured knockout fields written to the `jobs` row.
**Why agentic**: JD formats vary enormously; regex tail risk is high.
**Boundary**: only runs as a fallback after the deterministic parser misses;
output is structured + verifiable, not free-form prose.

### D. `jsa narrate-week` — weekly summary agent

**Trigger**: Sunday cron.
**Input**: weekly application + response data, scoring metadata.
**Action**: agent writes a 1–2 paragraph narrative summary of the week
(applied, responses, what's converting, what's not) for James's inbox.
**Output**: short markdown digest, emailed.
**Why agentic**: summarization is a strong LLM use case and the framing
choices matter for morale + decision-making.
**Boundary**: narrative is grounded in DB queries — no invented stats.

### E. `jsa scout-discipline` — strategy advisor agent

**Trigger**: on-demand.
**Input**: ENR rankings, recent ingested postings by discipline, James's
profile, current `config/scoring.yaml` discipline weights.
**Action**: agent answers "should James be applying to construction
management roles?" with current market evidence.
**Output**: a markdown brief; Steve/James decide whether to adjust
`discipline_weights` or `location.scheme`.
**Why agentic**: strategic question, requires synthesis of multiple sources.
**Boundary**: advisory only; no config changes.

---

## Anti-patterns — do not build

- ❌ **Agent in the daily ingestion path.** Cost, reliability, reproducibility
  all suffer. Use deterministic adapters.
- ❌ **Agent submitting applications.** Spec hard-no. James submits.
- ❌ **Agent rewriting `config/firms.yaml` autonomously.** Each heal that
  changes config should be a git commit — human review preserves the audit
  trail (per spec §10).
- ❌ **Agent acting as the matcher** (replacing the deterministic
  `CityMatcher` or discipline regex). Even where the agent is more flexible,
  the deterministic version is testable and the agentic version is not.

## Decision rule for adding a new agentic feature

Build it as a sidecar tool only if **all four** hold:

1. The task is bounded, infrequent (≤ weekly), and the output is
   human-reviewed before any state changes.
2. There's an explicit, structured output schema (not free-form prose
   except in narrative-summary cases).
3. There's a deterministic fallback if the agent fails or hallucinates.
4. The cost over a month is bounded by a calculable cap.

If any condition fails, build the deterministic version instead — or don't
build the feature.
