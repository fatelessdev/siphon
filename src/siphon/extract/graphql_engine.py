"""Async GraphQL extraction engine for Twitter/X.

Ported from twitter-cli client.py + graphql.py, converted to async
with curl_cffi AsyncSession and Siphon's stealth/auth modules.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import random
import re
import urllib.parse
from typing import Any

from curl_cffi import AsyncSession

from siphon.parse.models import Tweet, UserProfile
from siphon.parse.parse_stats import ParseStats
from siphon.stealth.header_fingerprint import build_headers
from siphon.stealth.transaction_id import TransactionIdManager

logger = logging.getLogger(__name__)

# ── Hard ceiling to prevent accidental massive fetches ───────────────────
_ABSOLUTE_MAX_COUNT = 500

# ── Community OpenAPI queryId source ─────────────────────────────────────
_TWITTER_OPENAPI_URL = (
    "https://raw.githubusercontent.com/fa0311/"
    "twitter-openapi/refs/heads/main/src/config/placeholder.json"
)

# ── Hardcoded fallback query IDs (from twitter-cli graphql.py) ───────────
FALLBACK_QUERY_IDS: dict[str, str] = {
    "HomeTimeline": "HCosKfLNW1AcOo3la3mMgg",
    "HomeLatestTimeline": "U0cdisy7QFIoTfu3-Okw0A",
    "UserByScreenName": "qRednkZG-rn1P6b48NINmQ",
    "UserTweets": "E3opETHurmVJflFsUBVuUQ",
    "TweetDetail": "nBS-WpgA6ZG0CyNHD517JQ",
    "Likes": "dv5-II7_Bup_PHish7p6fw",
    "SearchTimeline": "MJpyQGqgklrVl_0X9gNy3A",
    "Bookmarks": "uzboyXSHSJrR-mGJqep0TQ",
    "BookmarkTimeline": "uzboyXSHSJrR-mGJqep0TQ",
    "ListLatestTweetsTimeline": "ZBbXrl0FVnTqp7K6EAADog",
    "ListTimeline": "ZBbXrl0FVnTqp7K6EAADog",
    "Followers": "IOh4aS6UdGWGJUYTqliQ7Q",
    "Following": "zx6e-TLzRkeDO_a7p4b3JQ",
    "TweetResultByRestId": "7xflPyRiUxGVbJd4uWmbfg",
    "CreateTweet": "bDE2rBtZb3uyrczSZ_pI9g",
    "DeleteTweet": "VaenaVgh5q5ih7kvyVjgtg",
    "FavoriteTweet": "lI07N6Otwv1PhnEgXILM7A",
    "UnfavoriteTweet": "ZYKSe-w7KEslx3JhSIk5LA",
    "CreateRetweet": "ojPdsZsimiJrUGLR1sjVsA",
    "DeleteRetweet": "iQtK4dl5hBmXewYZuEOKVw",
    "CreateBookmark": "aoDbu3RHznuiSkQ9aNM67Q",
    "DeleteBookmark": "Wlmlj2-xISYCixDmuS8KNg",
}

# ── Default feature flags ────────────────────────────────────────────────
# Superset of twitter-cli's flags + our originals.  Merge, don't replace.
_DEFAULT_FEATURES: dict[str, bool] = {
    # From twitter-cli graphql.py
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "tweetypie_unmention_optimization_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "rweb_video_timestamps_enabled": True,
    "responsive_web_media_download_video_enabled": True,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "responsive_web_enhance_cards_enabled": False,
}

# Mutable feature flags — updated dynamically from x.com HTML
DEFAULT_FEATURES: dict[str, bool] = dict(_DEFAULT_FEATURES)

# ── Base variables for timeline endpoints ─────────────────────────────────
_TIMELINE_BASE_VARS: dict[str, Any] = {
    "includePromotedContent": False,
    "latestControlAvailable": True,
    "requestContext": "launch",
}


def _update_features_from_html(html: str) -> None:
    """Extract live feature flags from x.com HTML and update DEFAULT_FEATURES.

    Twitter embeds feature switch config in inline scripts on the homepage.
    Only UPDATES existing keys — never adds new ones to avoid URL bloat.
    """
    try:
        feature_pattern = re.compile(
            r'"([a-z][a-z0-9_]+)":\s*\{\s*"value"\s*:\s*(true|false)',
            re.IGNORECASE,
        )
        found = 0
        for match in feature_pattern.finditer(html):
            key = match.group(1)
            value = match.group(2).lower() == "true"
            if key in DEFAULT_FEATURES and DEFAULT_FEATURES[key] != value:
                DEFAULT_FEATURES[key] = value
                found += 1
        if found:
            logger.info("Updated %d feature flags from x.com", found)
    except Exception:
        pass


class TwitterAPIError(Exception):
    """Raised on non-retryable Twitter API errors."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(message)


class QueryIdError(Exception):
    """Raised when a query ID cannot be resolved for an operation."""


class GraphQLSession:
    """Async GraphQL engine using curl_cffi with Chrome TLS impersonation.

    Usage::

        async with AsyncSession(impersonate="chrome") as session:
            engine = GraphQLSession(session, ct0, tx_mgr)
            tweets = await engine.fetch_home_timeline(count=30)
    """

    def __init__(
        self,
        session: AsyncSession,
        ct0: str,
        transaction_id_mgr: TransactionIdManager | None = None,
        auth_token: str = "",
        cookie_string: str = "",
    ) -> None:
        self._session = session
        self._ct0 = ct0
        self._auth_token = auth_token
        self._cookie_string = cookie_string
        self._tx_mgr = transaction_id_mgr

        # In-memory query ID cache (per-session lifetime)
        self._query_id_cache: dict[str, str] = {}

        # Rate-limit / retry config
        self._max_retries = 3
        self._retry_base_delay = 5.0

        # JS bundle scan state
        self._bundles_scanned = False

    async def warm_up(self) -> None:
        """Fetch x.com homepage to sync live feature flags. Call before first API request."""
        try:
            resp = await self._session.get("https://x.com", timeout=15)
            resp.raise_for_status()
            _update_features_from_html(resp.text)
            logger.info("Warm-up complete — feature flags synced from x.com")
        except Exception as exc:
            logger.warning("Warm-up failed (using static feature flags): %s", exc)

    # ── Public read operations ───────────────────────────────────────

    async def fetch_home_timeline(self, count: int = 50) -> list[Tweet]:
        """Fetch the authenticated user's home timeline (algorithmic)."""
        return await self._fetch_timeline(
            operation_name="HomeTimeline",
            count=count,
            variables={},
            features=None,
        )

    async def fetch_following_feed(self, count: int = 50) -> list[Tweet]:
        """Fetch the authenticated user's following feed (chronological)."""
        return await self._fetch_timeline(
            operation_name="HomeLatestTimeline",
            count=count,
            variables={},
            features=None,
        )

    async def fetch_user_by_screen_name(self, screen_name: str) -> UserProfile | None:
        """Fetch a user profile by screen name."""
        variables: dict[str, Any] = {
            "screen_name": screen_name,
            "withSafetyModeUserFields": True,
        }
        features: dict[str, bool] = {
            "hidden_profile_subscriptions_enabled": True,
            "rweb_tipjar_consumption_enabled": True,
            "responsive_web_graphql_exclude_directive_enabled": True,
            "verified_phone_label_enabled": False,
            "subscriptions_verification_info_is_identity_verified_enabled": True,
            "subscriptions_verification_info_verified_since_enabled": True,
            "highlights_tweets_tab_ui_enabled": True,
            "responsive_web_twitter_article_notes_tab_enabled": True,
            "subscriptions_feature_can_gift_premium": True,
            "creator_subscriptions_tweet_preview_api_enabled": True,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
            "responsive_web_graphql_timeline_navigation_enabled": True,
        }
        data = await self._graphql_get("UserByScreenName", variables, features)
        result = _deep_get(data, "data", "user", "result")
        if not result:
            return None

        legacy = result.get("legacy", {})
        return UserProfile(
            id=int(result.get("rest_id", "0")),
            screen_name=legacy.get("screen_name", screen_name),
            name=legacy.get("name", ""),
            bio=legacy.get("description", ""),
            followers_count=_parse_int(legacy.get("followers_count"), 0),
            following_count=_parse_int(legacy.get("friends_count"), 0),
            tweets_count=_parse_int(legacy.get("statuses_count"), 0),
            verified=bool(result.get("is_blue_verified") or legacy.get("verified", False)),
            profile_image_url=legacy.get("profile_image_url_https", ""),
        )

    async def fetch_user_tweets(self, user_id: int, count: int = 50) -> list[Tweet]:
        """Fetch tweets posted by a user."""
        extra_vars: dict[str, Any] = {
            "userId": str(user_id),
            "withQuickPromoteEligibilityTweetFields": True,
            "withVoice": True,
            "withV2Timeline": True,
        }
        return await self._fetch_timeline(
            operation_name="UserTweets",
            count=count,
            variables=extra_vars,
            features=None,
        )

    # ── Core: paginated timeline fetcher ─────────────────────────────

    async def _fetch_timeline(
        self,
        operation_name: str,
        count: int,
        variables: dict[str, Any],
        features: dict[str, bool] | None = None,
    ) -> list[Tweet]:
        """Generic paginated timeline fetcher with dedup and jitter.

        Core of the engine. Handles cursor-based pagination, dedup by
        tweet ID, human-like timing jitter, and long pauses.
        """
        from siphon.parse.timeline_parser import parse_timeline_response

        if count <= 0:
            return []

        count = min(count, _ABSOLUTE_MAX_COUNT)
        effective_features = features or DEFAULT_FEATURES

        tweets: list[Tweet] = []
        seen_ids: set[int] = set()
        cursor: str | None = None
        page_count = 0
        max_attempts = int(math.ceil(count / 20.0)) + 2

        for _attempt in range(max_attempts):
            if len(tweets) >= count:
                break

            page_count += 1

            # Build page variables
            page_vars: dict[str, Any] = {
                "count": min(count - len(tweets) + 5, 40),
                **_TIMELINE_BASE_VARS,
                **variables,
            }
            if cursor:
                page_vars["cursor"] = cursor

            # Execute GraphQL request
            stats = ParseStats()
            data = await self._graphql_get(operation_name, page_vars, effective_features)
            new_tweets, next_cursor = parse_timeline_response(data, stats)

            # Log parse stats (parse_timeline_response already checked drop rate internally)
            logger.info(
                "Page %d [%s]: raw=%d parsed=%d dropped=%d (%.1f%%)",
                page_count,
                operation_name,
                stats.raw,
                stats.parsed,
                stats.raw - stats.parsed,
                stats.drop_rate,
            )

            # Dedup and collect
            for tweet in new_tweets:
                if tweet.id and tweet.id not in seen_ids:
                    seen_ids.add(tweet.id)
                    tweets.append(tweet)

            # Stop if no next cursor or cursor didn't advance
            if not next_cursor:
                logger.debug("No next cursor — pagination complete")
                break
            if next_cursor == cursor:
                logger.debug("Cursor did not advance — stopping pagination")
                break
            cursor = next_cursor

            if not new_tweets:
                logger.debug("Page returned no tweets but has cursor; continuing")

            # Rate-limit: sleep between paginated requests with jitter (matching twitter-cli)
            if len(tweets) < count:
                jitter = 2.5 * random.uniform(0.7, 1.5)
                await asyncio.sleep(jitter)

        return tweets[:count]

    # ── Core: single GraphQL GET with stale-fallback retry ───────────

    async def _graphql_get(
        self,
        operation_name: str,
        variables: dict[str, Any],
        features: dict[str, bool] | None = None,
        field_toggles: dict[str, bool] | None = None,
    ) -> dict[str, Any]:
        """Single GraphQL GET request with stale-fallback retry.

        If the first attempt returns 404/422 (stale query ID), invalidates
        the cache, re-resolves the query ID, and retries once.
        """
        effective_features = features or DEFAULT_FEATURES
        query_id = await self._resolve_query_id(operation_name)
        using_fallback = query_id == FALLBACK_QUERY_IDS.get(operation_name)
        url = self._build_graphql_url(query_id, operation_name, variables, effective_features, field_toggles)

        try:
            return await self._api_get(url)
        except TwitterAPIError as exc:
            # Stale query ID fallback retry
            if exc.status_code in (404, 422) and using_fallback:
                logger.info(
                    "Retrying %s with live queryId after HTTP %d",
                    operation_name,
                    exc.status_code,
                )
                self._invalidate_query_id(operation_name)
                refreshed_id = await self._resolve_query_id(operation_name)
                retry_url = self._build_graphql_url(
                    refreshed_id, operation_name, variables, effective_features, field_toggles
                )
                return await self._api_get(retry_url)
            raise

    # ── Core: query ID resolution (4-layer) ─────────────────────────

    async def _resolve_query_id(self, operation_name: str) -> str:
        """4-layer query ID resolution: cache → fallback → GitHub → JS bundle."""
        # Layer 1: In-memory cache
        cached = self._query_id_cache.get(operation_name)
        if cached:
            return cached

        # Layer 2: Hardcoded fallback
        fallback = FALLBACK_QUERY_IDS.get(operation_name)
        if fallback:
            self._query_id_cache[operation_name] = fallback
            return fallback

        # Layer 3: GitHub (twitter-openapi)
        github_id = await self._fetch_query_id_from_github(operation_name)
        if github_id:
            self._query_id_cache[operation_name] = github_id
            return github_id

        # Layer 4: JS bundle scan
        await self._scan_js_bundles()
        cached = self._query_id_cache.get(operation_name)
        if cached:
            return cached

        # Final fallback
        if fallback:
            self._query_id_cache[operation_name] = fallback
            return fallback

        raise QueryIdError(f'Cannot resolve queryId for "{operation_name}"')

    def _invalidate_query_id(self, operation_name: str) -> None:
        """Remove a cached query ID so it gets re-resolved."""
        self._query_id_cache.pop(operation_name, None)

    async def _fetch_query_id_from_github(self, operation_name: str) -> str | None:
        """Fetch query ID from community-maintained twitter-openapi repo."""
        try:
            resp = await self._session.get(_TWITTER_OPENAPI_URL, timeout=15)
            resp.raise_for_status()
            parsed = resp.json()
            operation = parsed.get(operation_name, {})
            query_id = operation.get("queryId")
            if isinstance(query_id, str) and query_id:
                logger.debug("GitHub queryId for %s: %s", operation_name, query_id)
                return query_id
        except Exception as exc:
            logger.debug("GitHub queryId lookup failed: %s", exc)
        return None

    async def _scan_js_bundles(self) -> None:
        """Scan Twitter JS bundles and cache queryId ↔ operationName pairs."""
        if self._bundles_scanned:
            return
        self._bundles_scanned = True

        try:
            resp = await self._session.get("https://x.com", timeout=15)
            resp.raise_for_status()
            html = resp.text

            # Update feature flags from HTML
            _update_features_from_html(html)

            script_pattern = re.compile(
                r'(?:src|href)=["\']'
                r'(https://abs\.twimg\.com/responsive-web/client-web[^"\']+\.js)'
                r'["\']'
            )
            script_urls = script_pattern.findall(html)
        except Exception as exc:
            logger.warning("Failed to fetch x.com for JS bundle scan: %s", exc)
            return

        scanned = 0
        for script_url in script_urls:
            try:
                bundle_resp = await self._session.get(script_url, timeout=15)
                bundle_resp.raise_for_status()
                bundle = bundle_resp.text

                op_pattern = re.compile(
                    r'queryId:\s*"([A-Za-z0-9_-]+)"[^}]{0,200}'
                    r'operationName:\s*"([^"]+)"'
                )
                for match in op_pattern.finditer(bundle):
                    qid, op_name = match.group(1), match.group(2)
                    self._query_id_cache.setdefault(op_name, qid)
                scanned += 1
            except Exception:
                continue

        logger.info(
            "Scanned %d JS bundles, cached %d query IDs",
            scanned,
            len(self._query_id_cache),
        )

    # ── URL / header builders ────────────────────────────────────────

    @staticmethod
    def _build_graphql_url(
        query_id: str,
        operation_name: str,
        variables: dict[str, Any],
        features: dict[str, bool],
        field_toggles: dict[str, bool] | None = None,
    ) -> str:
        """Build encoded GraphQL GET URL.

        Only includes True-valued feature flags to avoid 414 URI Too Long.
        Twitter's API defaults missing features to False.
        """
        compact_features = {k: v for k, v in features.items() if v is not False}
        url = (
            f"https://x.com/i/api/graphql/{query_id}/{operation_name}"
            f"?variables={urllib.parse.quote(json.dumps(variables, separators=(',', ':')))}"
            f"&features={urllib.parse.quote(json.dumps(compact_features, separators=(',', ':')))}"
        )
        if field_toggles:
            url += f"&fieldToggles={urllib.parse.quote(json.dumps(field_toggles, separators=(',', ':')))}"
        return url

    def _build_request_headers(self, url: str = "", method: str = "GET") -> dict[str, str]:
        """Build full request headers matching twitter-cli _build_headers() exactly.

        - Cookie header with auth_token + ct0
        - Full sec-ch-ua suite
        - X-Client-Transaction-Id if available
        """
        headers = build_headers(self._ct0, url=url, method=method)
        headers["x-twitter-auth-type"] = "OAuth2Session"

        # Cookie header (matching twitter-cli — NOT cookies= param)
        if self._cookie_string:
            headers["Cookie"] = self._cookie_string
        elif self._auth_token:
            headers["Cookie"] = f"auth_token={self._auth_token}; ct0={self._ct0}"

        # Generate x-client-transaction-id if available
        if self._tx_mgr and self._tx_mgr.available and url:
            try:
                tx_headers = self._tx_mgr.get_header(url=url, method=method)
                headers.update(tx_headers)
            except Exception as exc:
                logger.debug("Failed to generate transaction id: %s", exc)

        return headers

    # ── HTTP engine ──────────────────────────────────────────────────

    async def _api_get(self, url: str) -> dict[str, Any]:
        """Authenticated GET request with retry on rate limits."""
        headers = self._build_request_headers(url=url, method="GET")

        for attempt in range(self._max_retries + 1):
            resp = await self._session.get(url, headers=headers, timeout=30)
            status = resp.status_code

            # Rate limit — retry with backoff
            if status == 429 and attempt < self._max_retries:
                wait = self._retry_base_delay * (2**attempt) + random.uniform(0, 2)
                logger.warning(
                    "Rate limited (429), retrying in %.1fs (attempt %d/%d)",
                    wait,
                    attempt + 1,
                    self._max_retries,
                )
                await asyncio.sleep(wait)
                continue

            if status >= 400:
                raise TwitterAPIError(status, f"Twitter API error {status}: {resp.text[:500]}")

            try:
                payload = resp.json()
            except (json.JSONDecodeError, ValueError):
                raise TwitterAPIError(0, "Twitter API returned invalid JSON")

            # Check for JSON-level errors
            if isinstance(payload, dict) and payload.get("errors"):
                err = payload["errors"][0]
                err_msg = err.get("message", "Unknown error")
                err_code = err.get("code", 0)

                # JSON-level rate limit (code 88)
                if err_code == 88 and attempt < self._max_retries:
                    wait = self._retry_base_delay * (2**attempt) + random.uniform(0, 2)
                    logger.warning(
                        "Rate limited (code 88), retrying in %.1fs (attempt %d/%d)",
                        wait,
                        attempt + 1,
                        self._max_retries,
                    )
                    await asyncio.sleep(wait)
                    continue

                raise TwitterAPIError(0, f"Twitter API returned errors: {err_msg}")

            return payload

        raise TwitterAPIError(429, f"Rate limited after {self._max_retries} retries")


# ── Utility helpers ──────────────────────────────────────────────────────


def _deep_get(data: Any, *keys: Any) -> Any:
    """Safely traverse nested dicts/lists by key/index."""
    current = data
    for key in keys:
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(key)
        elif isinstance(current, (list, tuple)) and isinstance(key, int):
            try:
                current = current[key]
            except (IndexError, TypeError):
                return None
        else:
            return None
    return current


def _parse_int(value: Any, default: int = 0) -> int:
    """Parse a value to int, returning default on failure."""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default
