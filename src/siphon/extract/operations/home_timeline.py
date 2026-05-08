"""Home timeline scrape operation.

Orchestrates session creation, authentication, and timeline extraction
for the authenticated user's algorithmic home timeline.
"""

from __future__ import annotations

import logging

from curl_cffi import AsyncSession

from siphon.auth.cookie_provider import load_cookies
from siphon.extract.graphql_engine import GraphQLSession
from siphon.parse.models import Tweet
from siphon.stealth.header_fingerprint import best_chrome_target, sync_chrome_version
from siphon.stealth.transaction_id import TransactionIdManager

logger = logging.getLogger(__name__)


async def scrape_home_timeline(count: int = 50) -> list[Tweet]:
    """Scrape the authenticated user's home timeline.

    Creates a curl_cffi AsyncSession with Chrome TLS impersonation,
    initializes stealth headers and transaction ID, then paginates
    through the HomeTimeline GraphQL endpoint.

    Args:
        count: Maximum number of tweets to fetch (capped at 500).

    Returns:
        List of parsed Tweet objects.
    """
    cookies = load_cookies()
    target = best_chrome_target()
    sync_chrome_version(target)

    async with AsyncSession(impersonate=target) as session:
        # Initialize transaction ID manager (optional stealth layer)
        tx_mgr = TransactionIdManager()
        await tx_mgr.initialize(session)

        engine = GraphQLSession(
            session=session,
            ct0=cookies.ct0,
            transaction_id_mgr=tx_mgr,
            auth_token=cookies.auth_token,
            cookie_string=cookies.cookie_string,
        )

        tweets = await engine.fetch_home_timeline(count=count)
        logger.info("Fetched %d tweets from home timeline", len(tweets))
        return tweets
