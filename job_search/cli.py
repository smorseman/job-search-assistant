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
    """Generate today's daily review report and update Google Sheets."""
    from job_search.reporting import DailyReporter
    reporter = DailyReporter()
    stats = reporter.run()
    console.print(stats)


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
