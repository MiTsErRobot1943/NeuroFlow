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


def _normalize_plan_tasks(raw_tasks: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_tasks, list):
        return []

    tasks: list[dict[str, Any]] = []
    for item in raw_tasks:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        if not title:
            continue
        notes = str(item.get("notes", "")).strip()
        raw_subtasks = item.get("subtasks", [])
        subtasks = [str(sub).strip() for sub in raw_subtasks if str(sub).strip()] if isinstance(raw_subtasks, list) else []
        tasks.append({"title": title[:160], "notes": notes[:300], "subtasks": subtasks[:8]})
    return tasks[:8]


def _fallback_project_plan(profile: dict[str, Any], past_projects: list[dict[str, Any]]) -> dict[str, Any]:
    project_name = str(profile.get("project_name") or "Custom Project").strip() or "Custom Project"
    project_type = str(profile.get("project_type") or "web").strip() or "web"
    experience_level = str(profile.get("experience_level") or "beginner").strip() or "beginner"
    language_framework = str(profile.get("language_framework") or "").strip() or "stack not specified"
    time_management_style = str(profile.get("time_management_style") or "structured").strip()
    memory_style = str(profile.get("memory_style") or "mixed").strip()

    prior_names = ", ".join(item.get("name", "") for item in past_projects[:3] if item.get("name"))
    prior_context = prior_names or "none logged yet"

    return {
        "list_name": project_name,
        "tasks": [
            {
                "title": "Define scope and success criteria",
                "notes": (
                    f"Type: {project_type}. Experience: {experience_level}. "
                    f"Target stack: {language_framework}."
                ),
                "subtasks": [
                    "Write one-sentence project outcome",
                    "List required features for version 1",
                    "Capture non-goals to prevent scope creep",
                ],
            },
            {
                "title": "Set up implementation baseline",
                "notes": f"Use a {time_management_style} planning rhythm with milestones sized for weekly delivery.",
                "subtasks": [
                    "Create repository structure and starter README",
                    "Configure linting/testing baseline",
                    "Build first end-to-end vertical slice",
                ],
            },
            {
                "title": "Build memory-friendly execution system",
                "notes": f"Memory style: {memory_style}. Keep references and examples close to each task.",
                "subtasks": [
                    "Create checklist template for repeated workflows",
                    "Log design decisions as short notes",
                    "Review and refine plan every 2-3 sessions",
                ],
            },
            {
                "title": "Compare with past project patterns",
                "notes": f"Past projects from analytics: {prior_context}.",
                "subtasks": [
                    "Reuse proven setup choices from prior projects",
                    "Avoid previous bottlenecks",
                    "Define a retrospective checkpoint",
                ],
            },
        ],
    }


def generate_project_plan(
    profile: dict[str, Any],
    past_projects: list[dict[str, Any]],
) -> dict[str, Any]:
    fallback = _fallback_project_plan(profile, past_projects)
    if ollama is None:
        return fallback

    model = os.getenv("OLLAMA_MODEL", "mistral")
    base_url = os.getenv("OLLAMA_BASE_URL")
    client = ollama.Client(host=base_url) if base_url else ollama.Client()

    prompt = (
        "You are generating a personalized software project task layout. "
        "Return JSON only with keys: list_name (string), tasks (array). "
        "Each task item must include title (string), notes (string), subtasks (array of 2-5 concise strings). "
        "Generate 4-6 tasks ordered from planning to delivery."
        f"\nUser project profile: {json.dumps(profile)}"
        f"\nPast projects from analytics: {json.dumps(past_projects)}"
    )

    try:
        response = client.generate(model=model, prompt=prompt)
        raw = response.get("response", "") if isinstance(response, dict) else str(response)
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            return fallback

        list_name = str(parsed.get("list_name") or fallback["list_name"]).strip() or fallback["list_name"]
        tasks = _normalize_plan_tasks(parsed.get("tasks"))
        if not tasks:
            tasks = fallback["tasks"]
        return {"list_name": list_name[:80], "tasks": tasks}
    except Exception as exc:  # pragma: no cover - network/model dependent
        logger.warning("Project-plan fallback due to model error: %s", exc)
        return fallback


