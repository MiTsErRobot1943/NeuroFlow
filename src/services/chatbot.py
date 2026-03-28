"""Chatbot orchestration for task-aware assistance and direct task creation intent extraction."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from src.logging_config import setup_logger

logger = setup_logger(__name__)

_CREATE_TASK_PATTERN = re.compile(r"^(?:create|add)\s+task\s*[:\-]?\s*(.+)$", re.IGNORECASE)


try:
    import ollama
except ImportError:  # pragma: no cover - optional dependency at runtime
    ollama = None


def _fallback_response(message: str, tasks: list[dict[str, Any]]) -> dict[str, Any]:
    match = _CREATE_TASK_PATTERN.match(message.strip())
    if match:
        title = match.group(1).strip()[:160]
        return {
            "message": f"Created a task draft for: {title}",
            "action": "create_task",
            "task": {
                "title": title,
                "notes": "Created via chatbot fallback",
                "subtasks": [],
                "list_name": "General",
            },
        }

    recent_titles = ", ".join(task["title"] for task in tasks[:3]) if tasks else "none yet"
    return {
        "message": (
            "I can help create tasks. Try: 'create task: Build API auth layer'. "
            f"Recent tasks: {recent_titles}."
        ),
        "action": "none",
    }


def _coerce_response(data: str, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        parsed = json.loads(data)
        if isinstance(parsed, dict) and "message" in parsed:
            return parsed
    except json.JSONDecodeError:
        pass
    return fallback


def generate_response(
    message: str,
    tasks: list[dict[str, Any]],
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fallback = _fallback_response(message, tasks)

    if ollama is None:
        return fallback

    model = os.getenv("OLLAMA_MODEL", "mistral")
    base_url = os.getenv("OLLAMA_BASE_URL")
    client = ollama.Client(host=base_url) if base_url else ollama.Client()

    profile_text = ""
    if profile:
        profile_text = (
            f"Profile: web={profile.get('web_experience', 'unknown')}, "
            f"desktop={profile.get('desktop_experience', 'unknown')}, "
            f"architecture={profile.get('architecture_experience', 'unknown')}, "
            f"database={profile.get('database_experience', 'unknown')}"
        )

    task_preview = [
        {
            "title": task.get("title", ""),
            "done": bool(task.get("done", False)),
            "list_name": task.get("list_name", "General"),
        }
        for task in tasks[:8]
    ]

    prompt = (
        "You are NeuroFlow's assistant. Respond with JSON only and keys: "
        "message (string), action ('none' or 'create_task'), task (object when action=create_task). "
        "If action=create_task include task.title, task.notes, task.subtasks (array of strings), "
        "task.list_name. Keep concise.\n"
        f"User message: {message}\n"
        f"Task history: {json.dumps(task_preview)}\n"
        f"{profile_text}"
    )

    try:
        response = client.generate(model=model, prompt=prompt)
        raw = response.get("response", "") if isinstance(response, dict) else str(response)
        return _coerce_response(raw, fallback)
    except Exception as exc:  # pragma: no cover - network/model dependent
        logger.warning("Chatbot fallback due to model error: %s", exc)
        return fallback

