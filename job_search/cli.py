"""CLI entry point: `jsa <command>`"""

import logging

import click
from rich.logging import RichHandler
from rich.console import Console

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
    from job_search.tracking import advance_state
    from job_search.reporting import SelectionProcessor

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
    """Print funnel statistics."""
    from job_search.db import get_db
    with get_db() as db:
        rows = db.execute(
            "SELECT app_state, count(*) as cnt FROM jobs GROUP BY app_state ORDER BY cnt DESC"
        ).fetchall()
        console.print("\n[bold]Application funnel:[/bold]")
        for row in rows:
            console.print(f"  {row['app_state']:20} {row['cnt']:>5}")

        source_rows = db.execute(
            "SELECT source, count(*) as total, avg(match_score) as avg_score FROM jobs GROUP BY source ORDER BY total DESC"
        ).fetchall()
        console.print("\n[bold]By source:[/bold]")
        for row in source_rows:
            console.print(f"  {row['source']:20} {row['total']:>5} jobs  avg score {row['avg_score'] or 0:.2f}")
