"""Chatbot orchestration for task-aware assistance and direct task creation intent extraction."""

from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib.parse import quote_plus
from urllib.request import Request
from urllib.request import urlopen

from src.logging_config import setup_logger

logger = setup_logger(__name__)

_CREATE_TASK_PATTERN = re.compile(r"^(?:create|add)\s+task\s*[:\-]?\s*(.+)$", re.IGNORECASE)
_CREATE_TASK_BROAD_PATTERNS = [
    re.compile(
        r"^(?:create|add|set[\s-]*up|setup|prepare|plan)\s+"
        r"(?:a\s+|an\s+|the\s+)?"
        r"(?:project\s+)?(?:tasks|task|steps|step|project\s+plan|project\s+steps|plan)"
        r"(?:\s+(?:for|on|about|around|by))?\s*[:\-]?\s*(?P<title>.+)$",
        re.IGNORECASE,
    ),
]
_CODE_SNIPPET_PATTERN = re.compile(
    r"\b(code\s+snippet|syntax|example\s+code|show\s+code|how\s+to\s+write)\b",
    re.IGNORECASE,
)
_WEB_SEARCH_PATTERN = re.compile(
    r"\b(search\s+the\s+web|search\s+web|look\s+up|find\s+online|web\s+search|google)\b",
    re.IGNORECASE,
)

_CS_KEYWORDS = {
    "algorithm",
    "algorithms",
    "data structure",
    "big o",
    "complexity",
    "python",
    "javascript",
    "java",
    "c++",
    "sql",
    "api",
    "flask",
    "database",
    "query",
    "function",
    "class",
    "loop",
    "array",
    "list",
    "dictionary",
    "recursion",
    "debug",
    "testing",
    "project",
    "task",
}

_SNIPPET_LIBRARY = {
    "python": {
        "loop": (
            "```python\n"
            "items = ['auth', 'db', 'tests']\n"
            "for idx, item in enumerate(items, start=1):\n"
            "    print(f'{idx}. {item}')\n"
            "```"
        ),
        "function": (
            "```python\n"
            "def build_task(title: str, done: bool = False) -> dict[str, object]:\n"
            "    return {'title': title, 'done': done}\n"
            "```"
        ),
    },
    "javascript": {
        "async": (
            "```javascript\n"
            "async function fetchTasks() {\n"
            "  const res = await fetch('/api/tasks', { credentials: 'same-origin' });\n"
            "  const data = await res.json();\n"
            "  return data.tasks || [];\n"
            "}\n"
            "```"
        ),
        "array": (
            "```javascript\n"
            "const doneTasks = tasks\n"
            "  .filter(task => task.done)\n"
            "  .map(task => task.title);\n"
            "```"
        ),
    },
    "sql": {
        "join": (
            "```sql\n"
            "SELECT t.id, t.title, l.name AS list_name\n"
            "FROM tasks t\n"
            "JOIN task_lists l ON l.id = t.list_id\n"
            "WHERE t.user_id = ?;\n"
            "```"
        ),
        "group": (
            "```sql\n"
            "SELECT source, COUNT(*) AS created_count\n"
            "FROM tasks\n"
            "GROUP BY source\n"
            "ORDER BY created_count DESC;\n"
            "```"
        ),
    },
}


def _extract_task_draft_title(message: str) -> str | None:
    normalized = re.sub(r"\s+", " ", message.strip())
    if not normalized:
        return None

    match = _CREATE_TASK_PATTERN.match(normalized)
    if match:
        title = match.group(1).strip()
        return title[:160] if title else None

    for pattern in _CREATE_TASK_BROAD_PATTERNS:
        broad_match = pattern.match(normalized)
        if not broad_match:
            continue

        title = str(broad_match.group("title") or "").strip()
        title = re.sub(r"^(?:for|on|about|around|by)\s+", "", title, flags=re.IGNORECASE)
        title = re.sub(r"^(?:plan|tasks?|steps?)\s+(?:for\s+)?", "", title, flags=re.IGNORECASE)
        title = title.strip(" .:-")
        if title:
            return title[:160]

    return None


def _looks_like_cs_or_project_question(message: str) -> bool:
    lowered = message.lower()
    return any(token in lowered for token in _CS_KEYWORDS)


def _looks_like_task_listing_request(message: str) -> bool:
    lowered = message.lower().strip()
    return bool(
        re.search(r"\b(show|list|view|display)\s+(?:my\s+)?tasks?\b", lowered)
        or re.search(r"\bwhat\s+tasks?\s+do\s+i\s+have\b", lowered)
    )


def _select_snippet(message: str) -> tuple[str, str] | None:
    lowered = message.lower()
    if "python" in lowered:
        if "function" in lowered or "def" in lowered:
            return "python", _SNIPPET_LIBRARY["python"]["function"]
        return "python", _SNIPPET_LIBRARY["python"]["loop"]
    if "javascript" in lowered or "js" in lowered:
        if "async" in lowered or "await" in lowered or "fetch" in lowered:
            return "javascript", _SNIPPET_LIBRARY["javascript"]["async"]
        return "javascript", _SNIPPET_LIBRARY["javascript"]["array"]
    if "sql" in lowered or "query" in lowered:
        if "group" in lowered or "count" in lowered:
            return "sql", _SNIPPET_LIBRARY["sql"]["group"]
        return "sql", _SNIPPET_LIBRARY["sql"]["join"]
    return None


def _fallback_cs_help(message: str) -> dict[str, Any]:
    snippet = _select_snippet(message)
    if snippet:
        language, code_block = snippet
        return {
            "message": (
                f"Here is a {language} example you can adapt:\n\n"
                f"{code_block}\n\n"
                "Tip: tell me the exact concept (loops, functions, SQL joins, async fetch) "
                "and I can tailor it to your current task."
            ),
            "action": "none",
            "topic": "code_snippet",
        }

    return {
        "message": (
            "I can help with CS and project questions (algorithms, data structures, APIs, SQL, debugging, testing). "
            "If you want syntax practice, ask for a code snippet in Python, JavaScript, or SQL."
        ),
        "action": "none",
        "topic": "cs_help",
    }


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


def _search_web(query: str, max_results: int = 3) -> list[dict[str, str]]:
    endpoint = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
    request = Request(endpoint, headers={"User-Agent": "Mozilla/5.0 NeuroFlow/1.0"})

    with urlopen(request, timeout=7) as response:  # nosec B310 - trusted HTTPS endpoint
        html = response.read().decode("utf-8", errors="ignore")

    pattern = re.compile(
        r'<a[^>]*class="result__a"[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
        re.IGNORECASE,
    )
    matches = pattern.finditer(html)

    results: list[dict[str, str]] = []
    for match in matches:
        href = str(match.group("href") or "").strip()
        title = _strip_tags(str(match.group("title") or "")).strip()
        if not href or not title:
            continue
        results.append({"title": title, "url": href})
        if len(results) >= max_results:
            break

    return results


def _web_search_response(message: str, allow_web_search: bool) -> dict[str, Any]:
    query = re.sub(r"\b(search\s+the\s+web|search\s+web|look\s+up|find\s+online|web\s+search|google)\b", "", message, flags=re.IGNORECASE).strip(" .:-")
    if not query:
        query = message.strip()

    if not allow_web_search:
        return {
            "message": (
                "I can search the web for that, but I need your permission first. "
                "Approve web search?"
            ),
            "action": "request_web_permission",
            "web_query": query,
        }

    try:
        results = _search_web(query)
    except Exception as exc:  # pragma: no cover - network dependent
        logger.warning("Web search failed: %s", exc)
        return {
            "message": "I could not reach web search right now. Please try again shortly.",
            "action": "none",
            "topic": "web_search_error",
        }

    if not results:
        return {
            "message": f"No web results found for: {query}",
            "action": "none",
            "topic": "web_search",
        }

    formatted = "\n".join(f"- {item['title']}: {item['url']}" for item in results)
    return {
        "message": f"Top web results for '{query}':\n{formatted}",
        "action": "web_search_results",
        "results": results,
    }


try:
    import ollama
except ImportError:  # pragma: no cover - optional dependency at runtime
    ollama = None


def _fallback_response(
    message: str,
    tasks: list[dict[str, Any]],
    allow_web_search: bool = False,
) -> dict[str, Any]:
    title = _extract_task_draft_title(message)
    if title:
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

    if _WEB_SEARCH_PATTERN.search(message):
        return _web_search_response(message, allow_web_search)

    if (
        _CODE_SNIPPET_PATTERN.search(message)
        or (
            _looks_like_cs_or_project_question(message)
            and not _looks_like_task_listing_request(message)
        )
    ):
        return _fallback_cs_help(message)


    recent_titles = ", ".join(task["title"] for task in tasks[:3]) if tasks else "none yet"
    return {
        "message": (
            "I can help create tasks. Try: 'create task: Build API auth layer' or "
            "'set up tasks for capstone backend project'. "
            "I can also answer CS/project questions and share syntax snippets. "
            "For non-project topics, I can search the web with your permission. "
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
    allow_web_search: bool = False,
) -> dict[str, Any]:
    fallback = _fallback_response(message, tasks, allow_web_search=allow_web_search)

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
        "message (string), action ('none' or 'create_task' or 'request_web_permission' or 'web_search_results'), "
        "task (object when action=create_task). "
        "If action=create_task include task.title, task.notes, task.subtasks (array of strings), "
        "task.list_name. Keep concise.\n"
        "For CS/project questions, provide clear conceptual help and short syntax examples when useful.\n"
        "For unrelated topics, ask web-search permission before browsing.\n"
        f"User message: {message}\n"
        f"Task history: {json.dumps(task_preview)}\n"
        f"Web search already approved for this request: {allow_web_search}\n"
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


