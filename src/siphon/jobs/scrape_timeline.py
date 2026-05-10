"""Scheduled scrape job — the main batch entry point."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from curl_cffi import AsyncSession

from siphon.auth.cookie_provider import load_cookies
from siphon.db.connection import (
    release_advisory_lock,
    release_lease_lock,
    try_advisory_lock,
    try_lease_lock,
)
from siphon.db.tweet_repository import complete_scrape_run, start_scrape_run, upsert_tweets
from siphon.extract.graphql_engine import GraphQLSession
from siphon.parse.models import Tweet
from siphon.stealth.header_fingerprint import best_chrome_target, sync_chrome_version
from siphon.stealth.transaction_id import TransactionIdManager

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "output"
_SCHEDULED_OPERATIONS = ("home", "following")


def resolve_scrape_operations(operation: str) -> tuple[str, ...]:
    """Normalize a requested scrape operation into concrete timeline operations."""
    normalized = operation.strip().lower()
    if normalized in {"scheduled", "both", "all"}:
        return _SCHEDULED_OPERATIONS
    if normalized in {"home", "for-you", "foryou"}:
        return ("home",)
    if normalized == "following":
        return ("following",)
    return (normalized,)


def _format_tweet(i: int, t: Tweet) -> str:
    """Format a single tweet as Markdown."""
    lines = [f"### [{i}] @{t.author_handle} ({t.created_at:%Y-%m-%d %H:%M UTC})"]
    lines.append("")
    lines.append(f"> {t.text}")
    if t.quoted_text:
        quoted_by = f"@{t.quoted_author_handle}" if t.quoted_author_handle else "quoted tweet"
        lines.append("")
        lines.append(f"> Quoting {quoted_by}: {t.quoted_text}")
    if t.reply_to_text:
        reply_to = f"@{t.reply_to_author_handle}" if t.reply_to_author_handle else "parent tweet"
        lines.append("")
        lines.append(f"> Replying to {reply_to}: {t.reply_to_text}")
    lines.append("")
    if t.urls:
        lines.append("")
        lines.append(f"URLs: {', '.join(t.urls)}")
    if t.media:
        lines.append("")
        lines.append(f"Media: {', '.join(m.url for m in t.media if m.url)}")
    lines.append("")
    return "\n".join(lines)


def _write_output(
    operation: str,
    tweets: list[Tweet],
    new_count: int,
    updated_count: int,
    new_ids: set[int],
    updated_ids: set[int],
    errors: list[dict],
    stealth_degraded: bool,
) -> Path:
    """Write scrape results to a timestamped .md file in output/."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = OUTPUT_DIR / f"scrape_{operation}_{ts}.md"

    now = datetime.now(timezone.utc).isoformat()
    status = "completed" if not errors else "failed"

    lines: list[str] = []
    lines.append("# Siphon Scrape Report")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|-------|-------|")
    lines.append(f"| **Timestamp** | {now} |")
    lines.append(f"| **Operation** | {operation} |")
    lines.append(f"| **Status** | {status} |")
    lines.append(f"| **Tweets fetched** | {len(tweets)} |")
    lines.append(f"| **New** | {new_count} |")
    lines.append(f"| **Updated** | {updated_count} |")
    lines.append(f"| **Stealth degraded** | {stealth_degraded} |")
    if errors:
        lines.append(f"| **Errors** | {json.dumps(errors)} |")
    lines.append("")

    # Split tweets into new and updated
    new_tweets = [(i, t) for i, t in enumerate(tweets, 1) if t.id in new_ids]
    updated_tweets = [(i, t) for i, t in enumerate(tweets, 1) if t.id in updated_ids]

    # ── New tweets section ───────────────────────────────────────────
    if new_tweets:
        lines.append("---")
        lines.append("")
        lines.append(f"## New Tweets ({new_count})")
        lines.append("")
        for i, t in new_tweets:
            lines.append(_format_tweet(i, t))

    # ── Updated tweets section ───────────────────────────────────────
    if updated_tweets:
        lines.append("---")
        lines.append("")
        lines.append(f"## Updated Tweets ({updated_count})")
        lines.append("_Engagement metrics refreshed — these tweets were already in the database._")
        lines.append("")
        for i, t in updated_tweets:
            lines.append(_format_tweet(i, t))

    out_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Output written to %s", out_path)
    return out_path


async def run_scrape(operation: str = "scheduled", count: int = 30) -> int:
    """Run a scrape operation.

    Returns exit code: 0=success, 1=error, 2=skipped/locked.
    """
    operations = resolve_scrape_operations(operation)
    if len(operations) > 1:
        logger.info("Starting scheduled scrape batch: %s", ", ".join(operations))
        exit_codes = []
        for op in operations:
            exit_codes.append(await run_scrape(operation=op, count=count))
        for code in exit_codes:
            if code != 0:
                return code
        return 0

    actual_op = operations[0]

    # Load cookies
    try:
        cookies = load_cookies()
    except ValueError as e:
        logger.error("Auth config error: %s", e)
        return 1

    # Acquire DB lock
    owner = os.environ.get("GITHUB_RUN_ID", f"local-{os.getpid()}")
    advisory_conn = None
    using_advisory = False

    # Try advisory lock first
    advisory_conn, lock_acquired = try_advisory_lock()
    if lock_acquired:
        using_advisory = True
    else:
        # Fallback to lease lock
        if not try_lease_lock(name="scheduled_scrape", owner=owner, ttl_minutes=30):
            logger.info("Another scrape is running. Skipping (status=skipped_overlap)")
            return 2

    # Start scrape run record
    run_id = start_scrape_run(
        operation=actual_op,
        metadata={
            "count": count,
            "owner": owner,
            "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        },
    )

    errors: list[dict] = []
    tweets: list[Tweet] = []
    tx_mgr = TransactionIdManager()
    stealth_degraded = False

    try:
        # Detect best Chrome impersonation target and sync headers
        chrome_target = best_chrome_target()
        sync_chrome_version(chrome_target)
        logger.info("Impersonating %s", chrome_target)

        async with AsyncSession(impersonate=chrome_target) as session:
            # Initialize transaction ID (soft-fail)
            await tx_mgr.initialize(session)
            if not tx_mgr.available:
                stealth_degraded = True
                logger.warning(
                    "Transaction ID unavailable — stealth degraded: %s", tx_mgr.error
                )

            # Create engine
            engine = GraphQLSession(
                session,
                cookies.ct0,
                tx_mgr,
                auth_token=cookies.auth_token,
                cookie_string=cookies.cookie_string,
            )
            await engine.warm_up()  # Sync feature flags from live x.com

            # Fetch tweets
            logger.info("Starting %s scrape (count=%d)", actual_op, count)
            if actual_op == "following":
                tweets = await engine.fetch_following_feed(count=count)
            elif actual_op == "home":
                tweets = await engine.fetch_home_timeline(count=count)
            else:
                logger.error("Unknown operation: %s", actual_op)
                errors.append({"code": "UNKNOWN_OPERATION", "message": actual_op})

            # Set source_operation on all parsed tweets
            for t in tweets:
                t.source_operation = actual_op

    except Exception as e:
        logger.error("Scrape failed: %s", e)
        errors.append({"code": "SCRAPE_ERROR", "message": str(e)})

    # Upsert tweets
    new_count, updated_count = 0, 0
    new_ids: set[int] = set()
    updated_ids: set[int] = set()
    if tweets:
        try:
            new_count, updated_count, new_ids, updated_ids = upsert_tweets(tweets, source_operation=actual_op)
        except Exception as e:
            logger.error("Database upsert failed: %s", e)
            errors.append({"code": "DB_ERROR", "message": str(e)})

    # Complete scrape run
    status = "completed" if not errors else "failed"
    complete_scrape_run(
        run_id=run_id,
        status=status,
        tweets_fetched=len(tweets),
        tweets_new=new_count,
        tweets_updated=updated_count,
        errors=errors,
        parse_stats={"stealth_degraded": stealth_degraded},
    )

    # Release lock
    if using_advisory and advisory_conn:
        release_advisory_lock(advisory_conn)
    else:
        release_lease_lock(name="scheduled_scrape")

    logger.info(
        "Scrape complete: %s | fetched=%d new=%d updated=%d errors=%d stealth_degraded=%s",
        status,
        len(tweets),
        new_count,
        updated_count,
        len(errors),
        stealth_degraded,
    )

    # Write human-readable output file
    try:
        _write_output(actual_op, tweets, new_count, updated_count, new_ids, updated_ids, errors, stealth_degraded)
    except Exception as e:
        logger.warning("Failed to write output file: %s", e)

    return 0 if not errors else 1
