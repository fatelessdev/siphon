"""Core timeline GraphQL response parser for Siphon.

Parses Twitter GraphQL timeline responses into Tweet model objects.
Handles all known entry types, wrapper patterns, and edge cases defensively.
Every parse failure increments a ParseStats counter — the parser NEVER crashes.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from siphon.normalize.text_normalizer import normalize_text
from siphon.parse.models import Tweet, TweetMedia
from siphon.parse.parse_stats import ParseStats

logger = logging.getLogger(__name__)

# Twitter date format: "Sat Mar 08 12:00:00 +0000 2026"
_TWITTER_DATE_FMT = "%a %b %d %H:%M:%S %z %Y"


# ── Utility helpers ──────────────────────────────────────────────────────


def _deep_get(data: Any, *keys: Any) -> Any:
    """Safely get nested dict/list values.  Supports int keys for list access."""
    current = data
    for key in keys:
        if current is None:
            return None
        if isinstance(key, int):
            if not isinstance(current, list) or key >= len(current):
                return None
            current = current[key]
        else:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
    return current


def _parse_int(value: Any, default: int = 0) -> int:
    """Best-effort integer conversion without float precision loss."""
    try:
        text = str(value).replace(",", "").strip()
        if not text:
            return default
        try:
            return int(text)
        except ValueError:
            return int(Decimal(text))
    except (TypeError, ValueError, InvalidOperation):
        return default


def _parse_twitter_date(date_str: str) -> datetime:
    """Parse Twitter date string into a timezone-aware datetime.

    Falls back to utcnow if parsing fails.
    """
    try:
        return datetime.strptime(date_str, _TWITTER_DATE_FMT)
    except (TypeError, ValueError):
        logger.debug("Failed to parse date: %s", date_str)
        return datetime.now(timezone.utc)


# ── Cursor extraction ────────────────────────────────────────────────────


def _extract_cursor(data: dict) -> str | None:
    """Extract Bottom cursor from timeline response.

    Walks the instructions array looking for TimelineTimelineCursor entries.
    """
    instructions = (
        _deep_get(data, "data", "home", "home_timeline_urt", "instructions")
        or _deep_get(data, "data", "search_by_raw_query", "search_timeline", "timeline", "instructions")
        or _deep_get(data, "data", "user", "result", "timeline_v2", "timeline", "instructions")
        or _deep_get(data, "data", "list", "tweets_timeline", "timeline", "instructions")
    )
    if not isinstance(instructions, list):
        return None

    for instruction in instructions:
        entries = instruction.get("entries") or []
        for entry in entries:
            content = entry.get("content", {})
            if content.get("entryType") == "TimelineTimelineCursor" and content.get("cursorType") == "Bottom":
                return content.get("value")
    return None


# ── Media / URL / Hashtag / Cashtag extraction ───────────────────────────


def _extract_media(legacy: dict) -> list[TweetMedia]:
    """Extract media items from tweet legacy extended_entities."""
    media: list[TweetMedia] = []
    for media_item in _deep_get(legacy, "extended_entities", "media") or []:
        media_type = media_item.get("type", "")
        if media_type == "photo":
            media.append(
                TweetMedia(
                    type="photo",
                    url=media_item.get("media_url_https", ""),
                    width=_deep_get(media_item, "original_info", "width"),
                    height=_deep_get(media_item, "original_info", "height"),
                )
            )
        elif media_type in {"video", "animated_gif"}:
            variants = media_item.get("video_info", {}).get("variants", [])
            mp4_variants = [v for v in variants if v.get("content_type") == "video/mp4"]
            mp4_variants.sort(key=lambda v: v.get("bitrate", 0), reverse=True)
            media.append(
                TweetMedia(
                    type=media_type,
                    url=(
                        mp4_variants[0]["url"]
                        if mp4_variants
                        else media_item.get("media_url_https", "")
                    ),
                    width=_deep_get(media_item, "original_info", "width"),
                    height=_deep_get(media_item, "original_info", "height"),
                )
            )
    return media


def _extract_urls(legacy: dict) -> list[str]:
    """Extract expanded URLs from entities."""
    return [
        item.get("expanded_url", "")
        for item in _deep_get(legacy, "entities", "urls") or []
        if item.get("expanded_url")
    ]


def _is_promoted_or_ad(tweet_data: dict, legacy: dict) -> bool:
    """Detect advertiser/promoted timeline entries that should not enter storage."""
    source = f"{tweet_data.get('source', '')} {legacy.get('source', '')}".lower()
    if "advertiser" in source or "promoted" in source:
        return True
    card = tweet_data.get("card")
    if isinstance(card, dict):
        card_legacy = card.get("legacy", {})
        card_name = str(card_legacy.get("name", "")).lower()
        if "promoted" in card_name:
            return True
    return False


def _unwrap_tweet_result(tweet_data: dict) -> dict:
    """Unwrap visibility wrappers around tweet results."""
    if tweet_data.get("__typename") == "TweetWithVisibilityResults" and tweet_data.get("tweet"):
        return tweet_data["tweet"]
    return tweet_data


def _extract_context_text(tweet_data: dict) -> str:
    legacy = tweet_data.get("legacy", {})
    note_text = _deep_get(tweet_data, "note_tweet", "note_tweet_results", "result", "text")
    return normalize_text(note_text or legacy.get("full_text", ""))


def _extract_embedded_tweet_context(tweet_data: dict) -> tuple[int | None, str | None, str | None]:
    tweet_data = _unwrap_tweet_result(tweet_data)
    legacy = tweet_data.get("legacy")
    core = tweet_data.get("core")
    if not isinstance(legacy, dict) or not isinstance(core, dict):
        return None, None, None

    _author_id, author_handle, _author_name = _extract_user_info(tweet_data)
    return (
        _parse_int(tweet_data.get("rest_id"), 0) or None,
        author_handle or None,
        _extract_context_text(tweet_data) or None,
    )


# ── User extraction ──────────────────────────────────────────────────────


def _extract_user_info(tweet_data: dict) -> tuple[int, str, str]:
    """Extract (author_id, author_handle, author_name) from tweet data.

    Handles both nested (core.user_results.result) and flat user structures.
    """
    # Standard path: core → user_results → result
    user_result = _deep_get(tweet_data, "core", "user_results", "result")
    if isinstance(user_result, dict):
        user_core = user_result.get("core", {})
        user_legacy = user_result.get("legacy", {})
        author_id = _parse_int(user_result.get("rest_id"), 0)
        author_handle = (
            user_core.get("screen_name")
            or user_legacy.get("screen_name")
            or ""
        )
        author_name = (
            user_core.get("name")
            or user_legacy.get("name")
            or ""
        )
        return author_id, author_handle, author_name

    # Fallback: legacy-level user data (some edge cases)
    user_legacy = tweet_data.get("legacy", {}).get("user", {})
    if isinstance(user_legacy, dict):
        return (
            _parse_int(user_legacy.get("id_str"), 0),
            user_legacy.get("screen_name", ""),
            user_legacy.get("name", ""),
        )

    return 0, "", ""


# ── Tweet result extraction ──────────────────────────────────────────────


def _extract_tweet_result(entry: dict) -> dict | None:
    """Extract the tweet result dict from various entry shapes.

    Handles:
    - TimelineTimelineItem: content.itemContent.tweet_results.result
    - TimelineTimelineModule items: item.itemContent.tweet_results.result
    - tweet_result / tweetResult key variations
    """
    content = entry.get("content", {})

    # Direct TimelineTimelineItem
    item_content = content.get("itemContent", {})
    result = _deep_get(item_content, "tweet_results", "result")
    if result:
        return result

    # Alternate key: tweetResult (camelCase)
    result = _deep_get(item_content, "tweetResult", "result")
    if result:
        return result

    # Nested items (TimelineTimelineModule unwrapped entries)
    for nested_item in content.get("items", []):
        result = _deep_get(nested_item, "item", "itemContent", "tweet_results", "result")
        if result:
            return result
        result = _deep_get(nested_item, "item", "itemContent", "tweetResult", "result")
        if result:
            return result

    return None


# ── Single tweet parsing ─────────────────────────────────────────────────


def _parse_single_tweet(
    tweet_data: dict,
    stats: ParseStats,
    depth: int,
    context_by_id: dict[int, tuple[str, str]] | None = None,
) -> Tweet | None:
    """Parse tweet data (after result extraction) into a Tweet model.

    Handles TweetWithVisibilityResults wrapper, TweetTombstone, retweet
    resolution, quote tweet recursive parsing, note_tweet extraction.
    """
    tweet_data = _unwrap_tweet_result(tweet_data)

    # Skip tombstones and unavailable
    typename = tweet_data.get("__typename", "")
    if typename in ("TweetTombstone", "TweetUnavailable"):
        stats.dropped_tombstone += 1
        return None

    legacy = tweet_data.get("legacy")
    if not isinstance(legacy, dict):
        stats.dropped_no_legacy += 1
        return None

    if _is_promoted_or_ad(tweet_data, legacy):
        stats.dropped_promoted += 1
        return None

    core = tweet_data.get("core")
    if not isinstance(core, dict):
        stats.dropped_no_legacy += 1
        return None

    # ── Retweet resolution ────────────────────────────────────────────
    rt_result = _deep_get(legacy, "retweeted_status_result", "result")
    is_retweet = isinstance(rt_result, dict)

    actual_data = tweet_data
    actual_legacy = legacy

    if is_retweet:
        # Unwrap visibility-wrapped retweet
        if rt_result.get("__typename") == "TweetWithVisibilityResults" and rt_result.get("tweet"):
            rt_result = rt_result["tweet"]

        rt_legacy = rt_result.get("legacy")
        rt_core = rt_result.get("core")
        if isinstance(rt_legacy, dict) and isinstance(rt_core, dict):
            actual_data = rt_result
            actual_legacy = rt_legacy
        else:
            stats.dropped_rt_unparseable += 1
            return None

    # ── Text extraction (prefer note_tweet) ───────────────────────────
    note_text = _deep_get(actual_data, "note_tweet", "note_tweet_results", "result", "text")
    text_raw = note_text or actual_legacy.get("full_text", "")

    # ── User extraction ───────────────────────────────────────────────
    author_id, author_handle, author_name = _extract_user_info(actual_data)
    if not author_handle and is_retweet:
        # For retweets, fall back to wrapper tweet's author if retweeted user missing
        author_id, author_handle, author_name = _extract_user_info(tweet_data)

    # ── Reply / conversation detection ────────────────────────────────
    reply_to_tweet_id = _parse_int(actual_legacy.get("in_reply_to_status_id_str"), 0) or None
    reply_to_author_handle = actual_legacy.get("in_reply_to_screen_name") or None
    reply_to_text: str | None = None
    if reply_to_tweet_id and context_by_id:
        parent_handle, parent_text = context_by_id.get(reply_to_tweet_id, (None, None))
        reply_to_author_handle = reply_to_author_handle or parent_handle
        reply_to_text = parent_text

    # ── Quote tweet (recursive, depth-limited) ────────────────────────
    quoted_author_handle: str | None = None
    quoted_text: str | None = None
    quoted_tweet_id: int | None = None
    quoted_result = _deep_get(actual_data, "quoted_status_result", "result")
    if isinstance(quoted_result, dict) and depth < 2:
        quoted_tweet_id, quoted_author_handle, quoted_text = _extract_embedded_tweet_context(quoted_result)

    # ── Media / URLs / Entities ───────────────────────────────────────
    media = _extract_media(actual_legacy)
    urls = _extract_urls(actual_legacy)

    # ── Build model ───────────────────────────────────────────────────
    try:
        text = normalize_text(text_raw)
        created_at = _parse_twitter_date(actual_legacy.get("created_at", ""))

        tweet = Tweet(
            id=_parse_int(actual_data.get("rest_id"), 0),
            author_id=author_id,
            author_handle=author_handle,
            author_name=author_name,
            created_at=created_at,
            text=text,
            reply_to_tweet_id=reply_to_tweet_id,
            reply_to_author_handle=reply_to_author_handle,
            reply_to_text=reply_to_text,
            quoted_tweet_id=quoted_tweet_id,
            quoted_author_handle=quoted_author_handle,
            quoted_text=quoted_text,
            urls=urls,
            media=media,
        )
        return tweet
    except Exception:
        logger.debug("Failed to build Tweet model for rest_id=%s", actual_data.get("rest_id"), exc_info=True)
        stats.dropped_schema_fail += 1
        return None


# ── Entry-level parsing ──────────────────────────────────────────────────


def parse_tweet_entry(
    entry: dict,
    stats: ParseStats,
    depth: int = 0,
    context_by_id: dict[int, tuple[str, str]] | None = None,
) -> Tweet | None:
    """Parse a single timeline entry into a Tweet or None.

    Increments appropriate ParseStats counters on every drop.
    Wrapped in broad try/except — must never crash.
    """
    stats.raw += 1
    try:
        tweet_result = _extract_tweet_result(entry)
        if tweet_result is None:
            stats.dropped_no_result += 1
            return None

        tweet = _parse_single_tweet(tweet_result, stats, depth, context_by_id=context_by_id)
        if tweet is not None:
            stats.parsed += 1
        return tweet

    except Exception:
        logger.debug("Unhandled exception parsing entry", exc_info=True)
        stats.dropped_exception += 1
        return None


# ── Timeline response parsing ────────────────────────────────────────────


def parse_timeline_response(data: dict, stats: ParseStats) -> tuple[list[Tweet], str | None]:
    """Parse a full GraphQL timeline response into tweets + next cursor.

    Supports multiple response shapes:
    - HomeTimeline: data.home.home_timeline_urt.instructions
    - SearchTimeline: data.search_by_raw_query.search_timeline.timeline.instructions
    - UserTimeline: data.user.result.timeline_v2.timeline.instructions
    - ListTimeline: data.list.tweets_timeline.timeline.instructions

    Returns (tweets, next_cursor). next_cursor is None when pagination is exhausted.
    """
    instructions = (
        _deep_get(data, "data", "home", "home_timeline_urt", "instructions")
        or _deep_get(data, "data", "search_by_raw_query", "search_timeline", "timeline", "instructions")
        or _deep_get(data, "data", "user", "result", "timeline_v2", "timeline", "instructions")
        or _deep_get(data, "data", "list", "tweets_timeline", "timeline", "instructions")
    )

    if not isinstance(instructions, list):
        logger.warning("No timeline instructions found in response")
        return [], None

    tweets: list[Tweet] = []
    next_cursor: str | None = None

    for instruction in instructions:
        entries = instruction.get("entries") or []
        for entry in entries:
            content = entry.get("content", {})
            entry_type = content.get("entryType", "")

            if entry_type == "TimelineTimelineItem":
                tweet = parse_tweet_entry(entry, stats)
                if tweet is not None:
                    tweets.append(tweet)

            elif entry_type == "TimelineTimelineModule":
                # Unwrap conversation threads / grouped tweets
                context_by_id: dict[int, tuple[str, str]] = {}
                for nested_item in content.get("items", []):
                    fake_entry = {"content": nested_item.get("item", nested_item)}
                    tweet_result = _extract_tweet_result(fake_entry)
                    if not isinstance(tweet_result, dict):
                        continue
                    tweet_result = _unwrap_tweet_result(tweet_result)
                    legacy = tweet_result.get("legacy")
                    core = tweet_result.get("core")
                    if isinstance(legacy, dict) and isinstance(core, dict):
                        _author_id, handle, _name = _extract_user_info(tweet_result)
                        tweet_id = _parse_int(tweet_result.get("rest_id"), 0)
                        text = _extract_context_text(tweet_result)
                        if tweet_id and handle and text:
                            context_by_id[tweet_id] = (handle, text)

                for nested_item in content.get("items", []):
                    fake_entry = {"content": nested_item.get("item", nested_item)}
                    tweet = parse_tweet_entry(fake_entry, stats, context_by_id=context_by_id)
                    if tweet is not None:
                        tweets.append(tweet)

            elif entry_type == "TimelineTimelineCursor":
                if content.get("cursorType") == "Bottom":
                    next_cursor = content.get("value")

    stats.check_drop_rate()
    return tweets, next_cursor
