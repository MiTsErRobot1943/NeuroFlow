"""Analytics database helpers with graceful fallback when PostgreSQL is unavailable."""

from __future__ import annotations

import json
from typing import Any

from src.logging_config import setup_logger

logger = setup_logger(__name__)

try:
    import psycopg2
except ImportError:  # pragma: no cover - optional dependency at runtime
    psycopg2 = None


def initialize_analytics_database(database_url: str | None) -> bool:
    if not database_url or psycopg2 is None:
        return False

    driver = psycopg2

    try:
        with driver.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS analytics_events (
                        id BIGSERIAL PRIMARY KEY,
                        event_type TEXT NOT NULL,
                        username TEXT NOT NULL,
                        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    """
                )
        return True
    except Exception as exc:  # pragma: no cover - network/db dependent
        logger.warning("Analytics DB initialization skipped: %s", exc)
        return False


def track_event(
    database_url: str | None,
    event_type: str,
    username: str,
    payload: dict[str, Any] | None = None,
) -> None:
    if not database_url or psycopg2 is None:
        return

    driver = psycopg2

    try:
        with driver.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO analytics_events (event_type, username, payload)
                    VALUES (%s, %s, %s::jsonb)
                    """,
                    (event_type, username, json.dumps(payload or {})),
                )
    except Exception as exc:  # pragma: no cover - network/db dependent
        logger.warning("Analytics event tracking skipped: %s", exc)

