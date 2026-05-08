from __future__ import annotations
import json
import logging
from typing import Any

import psycopg2
import psycopg2.extras

from siphon.db.connection import get_connection
from siphon.parse.models import Tweet

logger = logging.getLogger(__name__)

def upsert_tweets(tweets: list[Tweet], source_operation: str = "") -> tuple[int, int, set[int], set[int]]:
    """Insert or update tweets. Returns (new_count, updated_count, new_ids, updated_ids)."""
    if not tweets:
        return 0, 0, set(), set()

    new_count = 0
    updated_count = 0
    new_ids: set[int] = set()
    updated_ids: set[int] = set()

    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            for tweet in tweets:
                cur.execute("""
                    INSERT INTO tweets (
                        id, author_id, author_handle, author_name, created_at, lang,
                        text_raw, text_normalized, tweet_type, is_retweet, is_reply, is_quote,
                        parent_tweet_id, conversation_id,
                        likes, retweets, replies, quotes, views, bookmarks,
                        urls, media_urls, hashtags, cashtags,
                        source_operation, pinned, raw_json, scraped_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, NOW()
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        likes = EXCLUDED.likes,
                        retweets = EXCLUDED.retweets,
                        replies = EXCLUDED.replies,
                        quotes = EXCLUDED.quotes,
                        views = EXCLUDED.views,
                        bookmarks = EXCLUDED.bookmarks,
                        scraped_at = NOW()
                    RETURNING (xmax = 0) AS is_new
                """, (
                    tweet.id, tweet.author_id, tweet.author_handle, tweet.author_name,
                    tweet.created_at, tweet.lang,
                    tweet.text_raw, tweet.text_normalized, tweet.tweet_type,
                    tweet.is_retweet, tweet.is_reply, tweet.is_quote,
                    tweet.parent_tweet_id, tweet.conversation_id,
                    tweet.likes, tweet.retweets, tweet.replies, tweet.quotes,
                    tweet.views, tweet.bookmarks,
                    json.dumps(tweet.urls), json.dumps([m.model_dump() for m in tweet.media]),
                    json.dumps(tweet.hashtags), json.dumps(tweet.cashtags),
                    source_operation, tweet.pinned,
                    json.dumps(tweet.raw_json),
                ))
                result = cur.fetchone()
                if result and result["is_new"]:
                    new_count += 1
                    new_ids.add(tweet.id)
                else:
                    updated_count += 1
                    updated_ids.add(tweet.id)
        conn.commit()

    logger.info("Upserted %d tweets: %d new, %d updated", len(tweets), new_count, updated_count)
    return new_count, updated_count, new_ids, updated_ids

def start_scrape_run(operation: str, metadata: dict[str, Any] | None = None) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO scrape_runs (status, operation, metadata)
                VALUES ('running', %s, %s)
                RETURNING id
            """, (operation, json.dumps(metadata or {})))
            run_id = cur.fetchone()[0]
        conn.commit()
    return run_id

def complete_scrape_run(
    run_id: int,
    status: str,
    tweets_fetched: int = 0,
    tweets_new: int = 0,
    tweets_updated: int = 0,
    errors: list[dict] | None = None,
    cursor_resume: str | None = None,
    parse_stats: dict | None = None,
) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE scrape_runs SET
                    completed_at = NOW(),
                    status = %s,
                    tweets_fetched = %s,
                    tweets_new = %s,
                    tweets_updated = %s,
                    errors = %s,
                    cursor_resume = %s,
                    parse_stats = %s
                WHERE id = %s
            """, (
                status, tweets_fetched, tweets_new, tweets_updated,
                json.dumps(errors or []), cursor_resume,
                json.dumps(parse_stats) if parse_stats else None,
                run_id,
            ))
        conn.commit()
