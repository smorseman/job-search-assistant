"""CLI entry point: `jsa <command>`"""

import logging

import click
from rich.console import Console
from rich.logging import RichHandler

from job_search.config import settings

console = Console()


def _setup_logging():
    logging.basicConfig(
        level=settings.LOG_LEVEL,
        handlers=[RichHandler(rich_tracebacks=True)],
        format="%(message)s",
    )


@click.group()
def cli():
    """Job Search Assistant — civil engineering pipeline for James."""
    _setup_logging()


@cli.command()
def preflight():
    """Check that every API key, config file, and profile field is ready."""
    from job_search.preflight import run_preflight
    report = run_preflight()

    icon = {True: "[green]✓[/green]", False: "[red]✗[/red]"}
    by_sev = {"required": [], "recommended": [], "optional": []}
    for c in report.checks:
        by_sev.setdefault(c.severity, []).append(c)

    for sev in ("required", "recommended", "optional"):
        if not by_sev[sev]:
            continue
        console.print(f"\n[bold]{sev.title()}[/bold]")
        for c in by_sev[sev]:
            console.print(f"  {icon[c.ok]}  {c.name:32s}  {c.detail}")

    s = report.summary
    console.print(
        f"\n[bold]Result:[/bold] {s['required_ok']}/{s['required_total']} required · "
        f"{s['recommended_ok']}/{s['recommended_total']} recommended"
    )
    if report.all_required_ok:
        console.print("[green]Ready to run.[/green]")
    else:
        console.print("[red]Not ready — fix required items first.[/red]")


@cli.command()
def init_db():
    """Initialize the SQLite database schema."""
    from job_search.db import init_db as _init
    _init()
    console.print("[green]Database initialized.[/green]")


@cli.command()
@click.option("--dry-run", is_flag=True, default=False, help="Fetch but do not write to DB.")
def ingest(dry_run: bool):
    """Run daily job ingestion from all sources."""
    from job_search.ingestion import Ingestor
    ingestor = Ingestor(dry_run=dry_run or settings.DRY_RUN)
    ingestor.load_firms()
    stats = ingestor.run()
    console.print(stats)


@cli.command()
def report():
    """Present today's top-scored postings to the Sheet (no doc generation)."""
    from job_search.reporting import DailyReporter
    reporter = DailyReporter()
    stats = reporter.run()
    console.print(stats)


@cli.command(name="sync-sheet")
def sync_sheet():
    """Pull James's status edits from the Sheet into the DB."""
    from job_search.reporting import SelectionProcessor
    proc = SelectionProcessor()
    stats = proc.sync_from_sheet()
    console.print(stats)


@cli.command()
@click.argument("job_ids", nargs=-1)
@click.option("--force", is_flag=True, help="Regenerate even if docs already exist")
def generate(job_ids: tuple[str, ...], force: bool):
    """Generate resume + cover letter for selected jobs (LLM calls).

    With no arguments, generates docs for every job in 'selected' state
    that doesn't already have docs. Pass specific job IDs to target only those.
    """
    from job_search.reporting import SelectionProcessor
    proc = SelectionProcessor()
    stats = proc.generate_for_selected(
        job_ids=list(job_ids) if job_ids else None,
        force=force,
    )
    console.print(
        f"[bold]Generated {stats['generated']} sets of docs[/bold] "
        f"({stats['errors']} errors)"
    )
    for doc in stats["docs"]:
        console.print(
            f"  [green]{doc['title']}[/green] @ {doc['company']}\n"
            f"    Resume: {doc['resume_url']}\n"
            f"    Cover:  {doc['cover_url']}"
        )


@cli.command()
@click.argument("job_id")
def apply(job_id: str):
    """Mark a job as 'selected' and generate docs immediately."""
    from job_search.db import get_db
    from job_search.reporting import SelectionProcessor
    from job_search.tracking import advance_state

    with get_db() as db:
        ok = advance_state(db, job_id, "selected", note="jsa apply CLI")
        if not ok:
            console.print(f"[red]Could not advance {job_id} to 'selected' — invalid transition[/red]")
            return

    proc = SelectionProcessor()
    stats = proc.generate_for_selected(job_ids=[job_id])
    if stats["generated"] > 0:
        doc = stats["docs"][0]
        console.print(f"[green]Docs ready:[/green]\n  Resume: {doc['resume_url']}\n  Cover:  {doc['cover_url']}")
    else:
        console.print("[red]Doc generation failed — see logs[/red]")


@cli.command()
def followup():
    """Surface overdue follow-up actions."""
    from job_search.tracking import FollowUpEngine
    engine = FollowUpEngine()
    actions = engine.run()
    if not actions:
        console.print("[green]No follow-up actions due today.[/green]")
    else:
        for action in actions:
            console.print(f"[yellow]{action['action_type']}[/yellow] — {action['company']} / {action['title']} (due {action['due_date']})")


@cli.command()
@click.argument("firm_name")
@click.argument("website")
def discover_firm(firm_name: str, website: str):
    """Fingerprint a single firm and add it to the registry."""
    from job_search.discovery import RegistryBuilder
    builder = RegistryBuilder()
    config = builder.fingerprint_firm(firm_name, website)
    if config:
        valid = builder.validate(config)
        console.print(f"ATS: {config.ats_type.value} / Tier: {config.ats_tier.value} / Valid: {valid}")
        if valid:
            builder.upsert_to_config(config)
            console.print(f"[green]{firm_name} added to registry.[/green]")
    else:
        console.print(f"[red]Could not fingerprint {firm_name}[/red]")


@cli.command()
@click.argument("canonical_job_id")
@click.argument("new_state")
@click.option("--note", default=None)
def update_state(canonical_job_id: str, new_state: str, note: str | None):
    """Manually transition a job's application state."""
    from job_search.db import get_db
    from job_search.tracking import advance_state
    with get_db() as db:
        ok = advance_state(db, canonical_job_id, new_state, note)
        if ok:
            console.print(f"[green]{canonical_job_id} → {new_state}[/green]")
        else:
            console.print(f"[red]Invalid transition to '{new_state}' for {canonical_job_id}[/red]")


@cli.command(name="score-location")
@click.argument("city")
@click.option("--state", default=None, help="2-letter state code (helps disambiguate)")
@click.option("--scheme", default=None, help="balanced | fit_first | career_first | career_relax | career_only")
def score_location(city: str, state: str | None, scheme: str | None):
    """Score a single location against the 50-metro framework."""
    from job_search.location import LocationScorer
    s = LocationScorer(scheme=scheme or "balanced")
    result = s.score(city, state)
    console.print(f"\n[bold]Location:[/bold] {city}{', ' + state if state else ''}")
    console.print(f"[bold]Scheme:[/bold] {result.scheme}")
    if result.metro_id:
        console.print(f"[bold]Matched metro:[/bold] {result.metro_name} ({result.metro_id})")
        console.print(f"[bold]Match kind:[/bold] {result.match_kind} (confidence {result.confidence:.2f})")
        d = result.dimensions
        console.print(
            f"[bold]Dimensions[/bold] — CE:{d.ce:.1f} COL:{d.col:.1f} "
            f"Home:{d.home:.1f} MJ:{d.mj:.1f} Dating:{d.dating:.1f}"
        )
    else:
        console.print(f"[yellow]No ranked metro matched[/yellow] (kind={result.match_kind})")
    console.print(f"[bold cyan]Composite:[/bold cyan] {result.composite:.1f}/100  → normalized {result.normalized:.3f}")


@cli.command()
def stats():
    """Print funnel statistics: where applications are, which sources convert."""
    from rich.table import Table

    from job_search.reporting.funnel import FUNNEL_STAGES, FunnelReporter

    stats = FunnelReporter().compute()
    console.print(f"\n[bold]Total jobs in DB:[/bold] {stats.total_jobs}\n")

    # ── Funnel ─────────────────────────────────────────────────────────────
    console.print("[bold]Funnel (current state)[/bold]")
    t = Table(show_header=True, header_style="bold")
    t.add_column("State")
    t.add_column("Count", justify="right")
    t.add_column("Avg match", justify="right")
    for stage in FUNNEL_STAGES + ["rejected", "ghosted"]:
        n = stats.by_state.get(stage, 0)
        if n == 0:
            continue
        avg = stats.avg_match_by_state.get(stage, 0)
        t.add_row(stage, str(n), f"{avg:.3f}")
    console.print(t)

    # ── By source ──────────────────────────────────────────────────────────
    if stats.by_source:
        console.print("\n[bold]By source[/bold]")
        t = Table(show_header=True, header_style="bold")
        t.add_column("Source")
        for col in ("discovered", "presented", "selected", "applied", "rejected"):
            t.add_column(col, justify="right")
        for src, states in sorted(stats.by_source.items()):
            t.add_row(src, *(str(states.get(c, 0)) for c in ("discovered", "presented", "selected", "applied", "rejected")))
        console.print(t)

    # ── Response rates ─────────────────────────────────────────────────────
    if stats.response_rate_by_source:
        console.print("\n[bold]Response rates by source[/bold] (applied → got any response)")
        t = Table(show_header=True, header_style="bold")
        t.add_column("Source")
        t.add_column("Applied", justify="right")
        t.add_column("Responded", justify="right")
        t.add_column("Response %", justify="right")
        t.add_column("Screen %", justify="right")
        t.add_column("Interview %", justify="right")
        for src, r in sorted(stats.response_rate_by_source.items(),
                              key=lambda kv: -kv[1]["response_rate"]):
            t.add_row(
                src,
                str(r["applied"]),
                str(r["responded"]),
                f"{r['response_rate']:.1%}",
                f"{r['screen_rate']:.1%}",
                f"{r['interview_rate']:.1%}",
            )
        console.print(t)

    # ── Stretch breakdown ──────────────────────────────────────────────────
    if stats.by_stretch:
        console.print("\n[bold]Stretch category × outcome[/bold]")
        t = Table(show_header=True, header_style="bold")
        t.add_column("Stretch")
        for col in ("presented", "selected", "applied", "rejected", "ghosted"):
            t.add_column(col, justify="right")
        for stretch, states in sorted(stats.by_stretch.items()):
            t.add_row(stretch, *(str(states.get(c, 0)) for c in ("presented", "selected", "applied", "rejected", "ghosted")))
        console.print(t)

    # ── Median timing ──────────────────────────────────────────────────────
    if any(v is not None for v in stats.median_days.values()):
        console.print("\n[bold]Median days (state transition)[/bold]")
        for label, days in stats.median_days.items():
            if days is not None:
                console.print(f"  {label:25s} {days:.1f} days")
