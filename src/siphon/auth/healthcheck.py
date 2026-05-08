from __future__ import annotations

import json
import logging
import urllib.parse

from curl_cffi import AsyncSession

from siphon.auth.cookie_provider import load_cookies
from siphon.stealth.header_fingerprint import BEARER_TOKEN, build_headers

logger = logging.getLogger(__name__)

# ── GraphQL healthcheck: UserByScreenName for a known public account ─────
_HEALTHCHECK_QUERY_ID = "qRednkZG-rn1P6b48NINmQ"
_HEALTHCHECK_OPERATION = "UserByScreenName"
_HEALTHCHECK_TARGET = "twitter"

_HEALTHCHECK_VARIABLES: dict[str, object] = {
    "screen_name": _HEALTHCHECK_TARGET,
    "withSafetyModeUserFields": True,
}

_HEALTHCHECK_FEATURES: dict[str, bool] = {
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


def _build_healthcheck_url() -> str:
    """Build the GraphQL UserByScreenName URL matching engine conventions."""
    compact_features = {k: v for k, v in _HEALTHCHECK_FEATURES.items() if v is not False}
    variables = json.dumps(_HEALTHCHECK_VARIABLES, separators=(",", ":"))
    features = json.dumps(compact_features, separators=(",", ":"))
    return (
        f"https://x.com/i/api/graphql/{_HEALTHCHECK_QUERY_ID}/{_HEALTHCHECK_OPERATION}"
        f"?variables={urllib.parse.quote(variables)}"
        f"&features={urllib.parse.quote(features)}"
    )


async def verify_auth(session: AsyncSession) -> dict:
    """Verify auth by querying UserByScreenName via GraphQL.

    Uses the same x.com/i/api/graphql/ endpoint pattern, headers, and
    cookie-based auth that the GraphQL engine uses for actual scraping.
    Returns the parsed user result dict on success, empty dict on soft failure.
    """
    cookies = load_cookies()
    headers = build_headers(cookies.ct0)
    headers["authorization"] = f"Bearer {BEARER_TOKEN}"
    headers["x-twitter-auth-type"] = "OAuth2Session"
    headers["Cookie"] = cookies.header_value

    url = _build_healthcheck_url()

    try:
        resp = await session.get(url, headers=headers, timeout=30)

        if resp.status_code == 200:
            data = resp.json()
            # Walk into data.user.result to extract screen name
            result = data.get("data", {}).get("user", {}).get("result", {})
            legacy = result.get("legacy", {})
            screen_name = legacy.get("screen_name", _HEALTHCHECK_TARGET)
            logger.info("Auth OK: @%s (via GraphQL UserByScreenName)", screen_name)
            return data

        # 401/403 = definite auth failure
        if resp.status_code in (401, 403):
            raise RuntimeError(
                f"Auth failed: HTTP {resp.status_code} — "
                "your TWITTER_AUTH_TOKEN or TWITTER_CT0 may be expired"
            )

        # 404/422 = likely stale query ID — still means auth is probably OK
        if resp.status_code in (404, 422):
            logger.warning(
                "Healthcheck returned HTTP %d (likely stale queryId %s) — "
                "auth tokens are being accepted; engine will resolve fresh IDs at runtime",
                resp.status_code,
                _HEALTHCHECK_QUERY_ID,
            )
            return {"_healthcheck_status": "stale_queryid", "_http_status": resp.status_code}

        # Other errors — soft-fail
        logger.info("Auth verification inconclusive: HTTP %d", resp.status_code)
        return {}

    except RuntimeError:
        raise
    except Exception as e:
        logger.info("Auth verification skipped (request error: %s)", e)
        return {}
