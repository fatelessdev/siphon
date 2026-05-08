from __future__ import annotations
import logging
from contextlib import contextmanager
from typing import Generator

import psycopg2
import psycopg2.extras

from siphon.config import get_settings

logger = logging.getLogger(__name__)

def get_dsn() -> str:
    return get_settings().database_url

@contextmanager
def get_connection(autocommit: bool = False) -> Generator[psycopg2.extensions.connection, None, None]:
    dsn = get_dsn()
    conn = psycopg2.connect(dsn)
    conn.autocommit = autocommit
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def try_advisory_lock(lock_name: str = "siphon:scheduled_scrape") -> tuple[psycopg2.extensions.connection | None, bool]:
    """Attempt to acquire a PostgreSQL advisory lock. Returns (connection, acquired).
    Caller must close the connection when done."""
    dsn = get_dsn()
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (lock_name,))
            acquired = cur.fetchone()[0]
            return conn if acquired else None, acquired
    except Exception as e:
        logger.warning("Advisory lock failed (may be pooled connection): %s", e)
        conn.close()
        return None, False

def try_lease_lock(
    name: str = "scheduled_scrape",
    owner: str = "unknown",
    ttl_minutes: int = 30,
) -> bool:
    """Fallback lease-based lock using scrape_locks table."""
    with get_connection(autocommit=True) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO scrape_locks (name, locked_until, owner, updated_at)
                VALUES (%s, NOW() + make_interval(mins => %s), %s, NOW())
                ON CONFLICT (name) DO UPDATE
                SET locked_until = NOW() + make_interval(mins => %s),
                    owner = EXCLUDED.owner,
                    updated_at = NOW()
                WHERE scrape_locks.locked_until < NOW()
                RETURNING name
            """, (name, ttl_minutes, owner, ttl_minutes))
            result = cur.fetchone()
            return result is not None

def release_lease_lock(name: str = "scheduled_scrape") -> None:
    with get_connection(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM scrape_locks WHERE name = %s", (name,))

def release_advisory_lock(conn: psycopg2.extensions.connection, lock_name: str = "siphon:scheduled_scrape") -> None:
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(hashtext(%s))", (lock_name,))
        conn.close()
    except Exception:
        pass
