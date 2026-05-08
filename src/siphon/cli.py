"""Siphon CLI — Twitter/X ingestion engine."""
from __future__ import annotations

import asyncio
import sys

import click

from siphon.config import get_settings
from siphon.security.log_redactor import setup_redacted_logging


@click.group()
@click.option("--log-level", default=None, help="Log level (DEBUG, INFO, WARNING, ERROR)")
def cli(log_level: str | None) -> None:
    """Siphon — Twitter/X ingestion engine."""
    level = log_level or get_settings().siphon_log_level
    setup_redacted_logging(level)


# ── db subcommand group ─────────────────────────────────────────────────


@cli.group("db")
def db_group() -> None:
    """Database management commands."""


@db_group.command("migrate")
def db_migrate() -> None:
    """Run database migrations."""
    from siphon.db.migrations import run_migrations

    run_migrations()
    click.echo("Migrations applied successfully.")


# ── scrape subcommand group ─────────────────────────────────────────────


@cli.group("scrape")
def scrape_group() -> None:
    """Scrape commands."""


@scrape_group.command("following")
@click.option("--count", default=30, help="Number of tweets to fetch")
def scrape_following(count: int) -> None:
    """Scrape the following feed (chronological timeline)."""
    from siphon.jobs.scrape_timeline import run_scrape

    exit_code = asyncio.run(run_scrape(operation="following", count=count))
    sys.exit(exit_code)


@scrape_group.command("home")
@click.option("--count", default=30, help="Number of tweets to fetch")
def scrape_home(count: int) -> None:
    """Scrape the home feed (algorithmic timeline)."""
    from siphon.jobs.scrape_timeline import run_scrape

    exit_code = asyncio.run(run_scrape(operation="home", count=count))
    sys.exit(exit_code)


@scrape_group.command("for-you")
@click.option("--count", default=30, help="Number of tweets to fetch")
def scrape_for_you(count: int) -> None:
    """Scrape the For You feed (algorithmic home timeline)."""
    from siphon.jobs.scrape_timeline import run_scrape

    exit_code = asyncio.run(run_scrape(operation="for-you", count=count))
    sys.exit(exit_code)


@scrape_group.command("scheduled")
@click.option("--count", default=30, help="Number of tweets to fetch")
def scrape_scheduled(count: int) -> None:
    """Run the default scheduled scrape (For You + following feed)."""
    from siphon.jobs.scrape_timeline import run_scrape

    exit_code = asyncio.run(run_scrape(operation="scheduled", count=count))
    sys.exit(exit_code)


# ── standalone commands ─────────────────────────────────────────────────


@cli.command("healthcheck-auth")
def healthcheck_auth() -> None:
    """Verify Twitter authentication credentials."""
    from curl_cffi import AsyncSession

    from siphon.auth.healthcheck import verify_auth
    from siphon.stealth.header_fingerprint import best_chrome_target, sync_chrome_version

    async def _run() -> None:
        target = best_chrome_target()
        sync_chrome_version(target)
        async with AsyncSession(impersonate=target) as session:
            result = await verify_auth(session)
            if result:
                screen_name = result.get("data", {}).get("user", {}).get("result", {}).get("legacy", {}).get("screen_name", "")
                if screen_name:
                    click.echo(f"Auth OK: @{screen_name}")
                else:
                    click.echo("Auth OK (response received)")
            else:
                click.echo("Auth verification skipped (non-auth endpoint errors).")
                click.echo("This is OK — the scrape will verify on first real API call.")

    asyncio.run(_run())


if __name__ == "__main__":
    cli()
