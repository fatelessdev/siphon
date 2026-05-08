from __future__ import annotations
import logging
from pathlib import Path
from siphon.db.connection import get_connection

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).parent / "schema.sql"

def run_migrations() -> None:
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"Schema file not found: {SCHEMA_PATH}")
    sql = SCHEMA_PATH.read_text()
    with get_connection(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
    logger.info("Migrations applied successfully")
