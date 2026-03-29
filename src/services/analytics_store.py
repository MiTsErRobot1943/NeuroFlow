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


def list_recent_projects(
    database_url: str | None,
    username: str,
    limit: int = 6,
) -> list[dict[str, Any]]:
    if not database_url or psycopg2 is None or not username:
        return []

    driver = psycopg2
    discovered: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    try:
        with driver.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT event_type, payload, created_at
                    FROM analytics_events
                    WHERE username = %s
                    ORDER BY id DESC
                    LIMIT %s
                    """,
                    (username, max(limit * 5, 20)),
                )
                rows = cur.fetchall()

        for event_type, payload, created_at in rows:
            parsed_payload: dict[str, Any]
            if isinstance(payload, dict):
                parsed_payload = payload
            elif isinstance(payload, str):
                try:
                    parsed_payload = json.loads(payload)
                except json.JSONDecodeError:
                    parsed_payload = {}
            else:
                parsed_payload = {}

            project_name = str(
                parsed_payload.get("project_name")
                or parsed_payload.get("list_name")
                or parsed_payload.get("name")
                or ""
            ).strip()
            if not project_name:
                continue

            normalized_name = project_name.casefold()
            if normalized_name in seen_names:
                continue
            seen_names.add(normalized_name)

            project_type = str(
                parsed_payload.get("project_type")
                or parsed_payload.get("template")
                or parsed_payload.get("type")
                or "unknown"
            ).strip()
            discovered.append(
                {
                    "name": project_name,
                    "type": project_type,
                    "source": event_type,
                    "created_at": str(created_at),
                }
            )
            if len(discovered) >= limit:
                break

        return discovered
    except Exception as exc:  # pragma: no cover - network/db dependent
        logger.warning("Analytics project lookup skipped: %s", exc)
        return []


