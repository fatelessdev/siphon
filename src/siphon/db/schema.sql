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
    pinned_tweet_id BIGINT,
    raw_json JSONB NOT NULL DEFAULT '{}'::jsonb,
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
    lang VARCHAR(10),
    text_raw TEXT NOT NULL,
    text_normalized TEXT NOT NULL,
    tweet_type VARCHAR(20) NOT NULL DEFAULT 'tweet',
    is_retweet BOOLEAN DEFAULT FALSE,
    is_reply BOOLEAN DEFAULT FALSE,
    is_quote BOOLEAN DEFAULT FALSE,
    parent_tweet_id BIGINT,
    conversation_id BIGINT,
    likes INTEGER DEFAULT 0,
    retweets INTEGER DEFAULT 0,
    replies INTEGER DEFAULT 0,
    quotes INTEGER DEFAULT 0,
    views INTEGER DEFAULT 0,
    bookmarks INTEGER DEFAULT 0,
    urls JSONB DEFAULT '[]'::jsonb,
    media_urls JSONB DEFAULT '[]'::jsonb,
    hashtags JSONB DEFAULT '[]'::jsonb,
    cashtags JSONB DEFAULT '[]'::jsonb,
    source_operation VARCHAR(50) NOT NULL DEFAULT '',
    pinned BOOLEAN DEFAULT FALSE,
    raw_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    scraped_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tweets_author_id ON tweets(author_id);
CREATE INDEX IF NOT EXISTS idx_tweets_created_at ON tweets(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tweets_tweet_type ON tweets(tweet_type);
CREATE INDEX IF NOT EXISTS idx_tweets_conversation_id ON tweets(conversation_id) WHERE conversation_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tweets_scraped_at ON tweets(scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_tweets_text_fts ON tweets USING gin(to_tsvector('english', text_normalized));
CREATE INDEX IF NOT EXISTS idx_tweets_raw_json ON tweets USING gin(raw_json jsonb_path_ops);
CREATE INDEX IF NOT EXISTS idx_tweets_engagement ON tweets((likes + retweets * 2 + quotes * 3) DESC);

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
