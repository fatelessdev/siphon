# Siphon

Twitter/X ingestion engine. Scrapes, parses, and stores tweets from your authenticated timeline into PostgreSQL.

**MVP Status:** Read-only, GitHub Actions scheduled, designed for downstream consumers.

## What It Does

Siphon runs as a GitHub Actions cron job (hourly) that:
1. Authenticates with Twitter/X using your cookies
2. Fetches your For You feed and following feed
3. Parses tweets with defensive, schema-resilient parsing
4. Normalizes text (Unicode NFKC, HTML decode, smart quotes)
5. Upserts lean tweet rows into PostgreSQL
6. Records each run with full observability (parse stats, errors, stealth status)

## Architecture

```
GitHub Actions (cron) → Siphon CLI → GraphQL Engine → Parser → PostgreSQL
                                                      ↓
                                              Downstream (Sigil, etc.)
```

- **Single engine, dual auth mode:** curl_cffi with Chrome TLS impersonation for all requests
- **Stealth:** Browser-faithful headers, x-client-transaction-id (soft-fail), human-like jitter
- **Parser:** Handles TimelineTimelineItem, TimelineTimelineModule, TweetWithVisibilityResults, tombstones, retweets, quotes, note_tweet, articles, and drops promoted/advertiser entries
- **Storage:** PostgreSQL with lean tweet rows and indexed canonical text

## Quick Start

### 1. Fork/clone and install

```bash
cd siphon
pip install -e ".[dev]"
```

### 2. Set up environment

```bash
cp .env.example .env
# Edit .env with your Twitter cookies and DATABASE_URL
```

### 3. Run migrations

```bash
python -m siphon db migrate
```

### 4. Verify auth

```bash
python -m siphon healthcheck-auth
```

### 5. Run a scrape

```bash
python -m siphon scrape following --count 30
python -m siphon scrape home --count 50
```

### 6. Set up GitHub Actions

1. Add repository secrets:
   - `TWITTER_AUTH_TOKEN` — your auth_token cookie
   - `TWITTER_CT0` — your ct0 cookie
   - `TWITTER_COOKIE_STRING` — optional full browser Cookie header, matching `twitter-cli` browser-cookie mode
   - `DATABASE_URL` — your PostgreSQL connection string (use Neon direct, not pooled)
2. The workflow runs automatically every hour via cron
3. Manual dispatch available from Actions tab

## Commands

| Command | Description |
|---------|-------------|
| `python -m siphon scrape scheduled` | Run the default scheduled scrape (For You + following) |
| `python -m siphon scrape for-you --count 30` | Scrape For You feed |
| `python -m siphon scrape following --count 30` | Scrape following feed |
| `python -m siphon scrape home --count 50` | Scrape home timeline |
| `python -m siphon db migrate` | Apply database migrations |
| `python -m siphon healthcheck-auth` | Verify Twitter credentials |

## Database Schema

### tweets
Stores parsed tweet data with full-text search and compact context.

| Field | Type | Description |
|-------|------|-------------|
| id | BIGINT | Tweet snowflake ID (primary key) |
| author_id | BIGINT | Stable user ID for follow/profile scrape actions |
| author_handle | VARCHAR | @username |
| text | TEXT | Canonical normalized text, indexed for full-text search |
| reply_to_tweet_id/reply_to_author_handle/reply_to_text | mixed | Compact replied-to context when available |
| quoted_tweet_id/quoted_author_handle/quoted_text | mixed | Compact quote context when available |
| urls/media_urls | JSONB | Expanded links and media references |
| scraped_at | TIMESTAMPTZ | When this tweet was ingested |

### scrape_runs
Tracks each scrape execution for observability.

### scrape_locks
Prevents overlapping runs via advisory + lease-based locking.

## Downstream Integration (Sigil)

Siphon writes tweets. Sigil reads them. The boundary is the database.

Sigil can query unprocessed tweets:
```sql
SELECT * FROM tweets 
WHERE scraped_at > NOW() - INTERVAL '24 hours'
ORDER BY scraped_at ASC
LIMIT 100;
```

Siphon does not know about Sigil's prompts, scoring, or analysis logic.

## MVP Non-Goals

- No write operations (posting, liking, retweeting, etc.)
- No FastAPI server / always-on service
- No Docker deployment requirement
- No multi-account rotation
- No proxy system
- No public profile scraping / guest mode
- No keyword search
- No article extraction (framework exists, not wired up)

## Stealth Stack

| Layer | Status |
|-------|--------|
| curl_cffi Chrome TLS impersonation | Active |
| Browser-faithful sec-ch-ua headers | Active |
| x-client-transaction-id | Soft-fail (degraded if unavailable) |
| Human-like jitter (±20%) | Active |
| Log secret redaction | Active |
| Conservative rate limiting | Active (stops on 429) |

## License

Private — not for redistribution.
