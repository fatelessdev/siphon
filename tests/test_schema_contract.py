import re
from pathlib import Path


SCHEMA_SQL = Path(__file__).parent.parent / "src" / "siphon" / "db" / "schema.sql"


def _tweets_table_sql() -> str:
    schema = SCHEMA_SQL.read_text(encoding="utf-8")
    match = re.search(r"CREATE TABLE IF NOT EXISTS tweets \((.*?)\);", schema, re.S)
    assert match is not None
    return match.group(1)


def _schema_sql() -> str:
    return SCHEMA_SQL.read_text(encoding="utf-8")


def test_tweets_table_keeps_only_agent_useful_columns():
    tweets_table = _tweets_table_sql()

    assert re.search(r"\bauthor_id\s+BIGINT", tweets_table)
    assert re.search(r"\btext\s+TEXT NOT NULL", tweets_table)
    assert re.search(r"\bquoted_tweet_id\s+BIGINT", tweets_table)
    assert re.search(r"\bquoted_author_handle\s+VARCHAR\(50\)", tweets_table)
    assert re.search(r"\bquoted_text\s+TEXT", tweets_table)
    assert re.search(r"\breply_to_tweet_id\s+BIGINT", tweets_table)
    assert re.search(r"\breply_to_author_handle\s+VARCHAR\(50\)", tweets_table)
    assert re.search(r"\breply_to_text\s+TEXT", tweets_table)
    assert re.search(r"\bscraped_at\s+TIMESTAMPTZ NOT NULL", tweets_table)

    dropped_columns = [
        "lang",
        "text_raw",
        "text_normalized",
        "tweet_type",
        "is_retweet",
        "is_reply",
        "is_quote",
        "parent_tweet_id",
        "conversation_id",
        "likes",
        "retweets",
        "replies",
        "quotes",
        "views",
        "bookmarks",
        "hashtags",
        "cashtags",
        "pinned",
        "raw_json",
    ]
    for column in dropped_columns:
        assert not re.search(rf"\b{column}\b", tweets_table)


def test_migration_cleanup_does_not_drop_kept_columns():
    schema = _schema_sql()

    kept_columns = [
        "author_id",
        "reply_to_tweet_id",
        "quoted_tweet_id",
    ]
    for column in kept_columns:
        assert f"DROP COLUMN IF EXISTS {column}" not in schema
