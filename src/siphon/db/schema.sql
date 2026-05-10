-- Siphon Database Schema
-- Run with: python -m siphon db migrate

CREATE TABLE IF NOT EXISTS scrape_locks (
    name TEXT PRIMARY KEY,
    locked_until TIMESTAMPTZ NOT NULL,
    owner TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS users (
    id BIGINT PRIMARY KEY,
    screen_name VARCHAR(50) NOT NULL,
    name VARCHAR(200),
    bio TEXT,
    location VARCHAR(300),
    url TEXT,
    followers_count INTEGER DEFAULT 0,
    following_count INTEGER DEFAULT 0,
    tweets_count INTEGER DEFAULT 0,
    verified BOOLEAN DEFAULT FALSE,
    profile_image_url TEXT,
    last_scraped_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_screen_name ON users(screen_name);

CREATE TABLE IF NOT EXISTS tweets (
    id BIGINT PRIMARY KEY,
    author_id BIGINT NOT NULL,
    author_handle VARCHAR(50) NOT NULL,
    author_name VARCHAR(200) DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL,
    text TEXT NOT NULL,
    reply_to_tweet_id BIGINT,
    reply_to_author_handle VARCHAR(50),
    reply_to_text TEXT,
    quoted_tweet_id BIGINT,
    quoted_author_handle VARCHAR(50),
    quoted_text TEXT,
    urls JSONB DEFAULT '[]'::jsonb,
    media_urls JSONB DEFAULT '[]'::jsonb,
    source_operation VARCHAR(50) NOT NULL DEFAULT '',
    scraped_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE users DROP COLUMN IF EXISTS pinned_tweet_id;
ALTER TABLE users DROP COLUMN IF EXISTS raw_json;

ALTER TABLE tweets ADD COLUMN IF NOT EXISTS text TEXT;
ALTER TABLE tweets ADD COLUMN IF NOT EXISTS author_id BIGINT;
UPDATE tweets SET author_id = 0 WHERE author_id IS NULL;
ALTER TABLE tweets ALTER COLUMN author_id SET NOT NULL;
ALTER TABLE tweets ADD COLUMN IF NOT EXISTS reply_to_tweet_id BIGINT;
ALTER TABLE tweets ADD COLUMN IF NOT EXISTS reply_to_author_handle VARCHAR(50);
ALTER TABLE tweets ADD COLUMN IF NOT EXISTS reply_to_text TEXT;
ALTER TABLE tweets ADD COLUMN IF NOT EXISTS quoted_tweet_id BIGINT;
ALTER TABLE tweets ADD COLUMN IF NOT EXISTS quoted_author_handle VARCHAR(50);
ALTER TABLE tweets ADD COLUMN IF NOT EXISTS quoted_text TEXT;
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tweets' AND column_name = 'text_normalized'
    ) AND EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tweets' AND column_name = 'text_raw'
    ) THEN
        EXECUTE 'UPDATE tweets
                 SET text = COALESCE(NULLIF(text_normalized, ''''), NULLIF(text_raw, ''''), text)
                 WHERE text IS NULL OR text = ''''';
    ELSIF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tweets' AND column_name = 'text_normalized'
    ) THEN
        EXECUTE 'UPDATE tweets
                 SET text = COALESCE(NULLIF(text_normalized, ''''), text)
                 WHERE text IS NULL OR text = ''''';
    ELSIF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tweets' AND column_name = 'text_raw'
    ) THEN
        EXECUTE 'UPDATE tweets
                 SET text = COALESCE(NULLIF(text_raw, ''''), text)
                 WHERE text IS NULL OR text = ''''';
    END IF;
END $$;
ALTER TABLE tweets ALTER COLUMN text SET NOT NULL;

DROP INDEX IF EXISTS idx_tweets_author_id;
DROP INDEX IF EXISTS idx_tweets_tweet_type;
DROP INDEX IF EXISTS idx_tweets_conversation_id;
DROP INDEX IF EXISTS idx_tweets_text_fts;
DROP INDEX IF EXISTS idx_tweets_raw_json;
DROP INDEX IF EXISTS idx_tweets_engagement;

ALTER TABLE tweets DROP COLUMN IF EXISTS lang;
ALTER TABLE tweets DROP COLUMN IF EXISTS text_raw;
ALTER TABLE tweets DROP COLUMN IF EXISTS text_normalized;
ALTER TABLE tweets DROP COLUMN IF EXISTS tweet_type;
ALTER TABLE tweets DROP COLUMN IF EXISTS is_retweet;
ALTER TABLE tweets DROP COLUMN IF EXISTS is_reply;
ALTER TABLE tweets DROP COLUMN IF EXISTS is_quote;
ALTER TABLE tweets DROP COLUMN IF EXISTS parent_tweet_id;
ALTER TABLE tweets DROP COLUMN IF EXISTS conversation_id;
ALTER TABLE tweets DROP COLUMN IF EXISTS reply_to_tweet_id;
ALTER TABLE tweets DROP COLUMN IF EXISTS quoted_tweet_id;
ALTER TABLE tweets DROP COLUMN IF EXISTS likes;
ALTER TABLE tweets DROP COLUMN IF EXISTS retweets;
ALTER TABLE tweets DROP COLUMN IF EXISTS replies;
ALTER TABLE tweets DROP COLUMN IF EXISTS quotes;
ALTER TABLE tweets DROP COLUMN IF EXISTS views;
ALTER TABLE tweets DROP COLUMN IF EXISTS bookmarks;
ALTER TABLE tweets DROP COLUMN IF EXISTS hashtags;
ALTER TABLE tweets DROP COLUMN IF EXISTS cashtags;
ALTER TABLE tweets DROP COLUMN IF EXISTS pinned;
ALTER TABLE tweets DROP COLUMN IF EXISTS raw_json;

CREATE INDEX IF NOT EXISTS idx_tweets_created_at ON tweets(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tweets_scraped_at ON tweets(scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_tweets_text_fts ON tweets USING gin(to_tsvector('english', text));

CREATE TABLE IF NOT EXISTS scrape_runs (
    id SERIAL PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    status VARCHAR(20) NOT NULL DEFAULT 'running',
    operation VARCHAR(50) NOT NULL,
    tweets_fetched INTEGER DEFAULT 0,
    tweets_new INTEGER DEFAULT 0,
    tweets_updated INTEGER DEFAULT 0,
    errors JSONB DEFAULT '[]'::jsonb,
    cursor_resume TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    parse_stats JSONB
);

CREATE INDEX IF NOT EXISTS idx_scrape_runs_status ON scrape_runs(status);
CREATE INDEX IF NOT EXISTS idx_scrape_runs_started ON scrape_runs(started_at DESC);
