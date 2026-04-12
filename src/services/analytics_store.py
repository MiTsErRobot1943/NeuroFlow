"""Analytics database helpers with graceful fallback when PostgreSQL is unavailable."""

from __future__ import annotations

import json
import statistics
from collections import Counter
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


def get_user_feedback_context(
    database_url: str | None,
    username: str,
    limit: int = 120,
) -> dict[str, Any]:
    """Build lightweight analytics signals used to personalize AI outputs."""
    empty_result: dict[str, Any] = {
        "chatbot": {
            "top_intents": [],
            "action_counts": {},
            "avg_query_tokens": 0,
        },
        "tasks": {
            "completed_count": 0,
            "avg_completion_minutes": None,
            "median_completion_minutes": None,
        },
    }

    if not database_url or psycopg2 is None or not username:
        return empty_result

    driver = psycopg2

    try:
        with driver.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT event_type, payload
                    FROM analytics_events
                    WHERE username = %s
                    ORDER BY id DESC
                    LIMIT %s
                    """,
                    (username, max(limit, 20)),
                )
                rows = cur.fetchall()

        intent_counts: Counter[str] = Counter()
        action_counts: Counter[str] = Counter()
        query_token_counts: list[int] = []
        completion_minutes: list[float] = []

        for event_type, payload in rows:
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

            if event_type == "chatbot_interaction":
                raw_tags = parsed_payload.get("intent_tags", [])
                if isinstance(raw_tags, list):
                    for tag in raw_tags:
                        text = str(tag).strip().lower()
                        if text:
                            intent_counts[text] += 1

                action = str(parsed_payload.get("action", "")).strip().lower()
                if action:
                    action_counts[action] += 1

                token_count = parsed_payload.get("query_token_count")
                if isinstance(token_count, (int, float)) and token_count >= 0:
                    query_token_counts.append(int(token_count))

            if event_type == "task_completion":
                minutes = parsed_payload.get("completion_minutes")
                if isinstance(minutes, (int, float)) and minutes >= 0:
                    completion_minutes.append(float(minutes))

        avg_tokens = round(sum(query_token_counts) / len(query_token_counts), 2) if query_token_counts else 0
        avg_completion = (
            round(sum(completion_minutes) / len(completion_minutes), 2)
            if completion_minutes
            else None
        )
        median_completion = (
            round(float(statistics.median(completion_minutes)), 2)
            if completion_minutes
            else None
        )

        return {
            "chatbot": {
                "top_intents": [tag for tag, _ in intent_counts.most_common(3)],
                "action_counts": dict(action_counts),
                "avg_query_tokens": avg_tokens,
            },
            "tasks": {
                "completed_count": len(completion_minutes),
                "avg_completion_minutes": avg_completion,
                "median_completion_minutes": median_completion,
            },
        }
    except Exception as exc:  # pragma: no cover - network/db dependent
        logger.warning("Analytics feedback lookup skipped: %s", exc)
        return empty_result


