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
        r"^(?:create|add|set|set[\s-]*up|setup|prepare|plan)\s+"
        r"(?:a\s+|an\s+|the\s+)?"
        r"(?:project\s+)?(?:tasks|task|steps|step|project\s+plan|project\s+steps|plan)"
        r"(?:\s+(?:for|on|about|around|by))?\s*[:\-]?\s*(?P<title>.+)$",
        re.IGNORECASE,
    ),
]
_BUILD_APP_INTENT_PATTERNS = [
    re.compile(
        r"^(?:how\s+do\s+i\s+|how\s+to\s+|help\s+me\s+(?:to\s+)?)?(?:build|make|create|develop)\s+"
        r"(?:a\s+|an\s+|the\s+)?(?P<goal>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:set|setup|set\s+up|create|add|plan|prepare)\s+"
        r"(?:tasks?|steps?|plan)\s+(?:for|to)\s+"
        r"(?P<goal>(?:building|making|creating|developing)\s+.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^help\s+me\s+(?:set\s+up|setup|get\s+started\s+with|build|make|create|develop)\s+"
        r"(?:a\s+|an\s+|the\s+)?(?P<goal>.+)$",
        re.IGNORECASE,
    ),
]
_LEARNING_PLAN_PATTERNS = [
    re.compile(
        r"^(?:help\s+me\s+learn|teach\s+me|i\s+want\s+to\s+learn|learn)\s+(?P<topic>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^help\s+me\s+(?:get\s+started\s+with|learn|understand|master)\s+(?P<topic>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:create|add|set\s*up|setup|plan|prepare)\s+(?:a\s+|an\s+|the\s+)?"
        r"(?:learning\s+plan|study\s+plan|study\s+tasks?|learning\s+tasks?)\s+"
        r"(?:for\s+)?(?P<topic>.+)$",
        re.IGNORECASE,
    ),
]
_APP_NOUN_PATTERN = re.compile(
    r"\b(app|application|game|website|web\s*app|tool|platform|api|system|browser\s+game|chatbot|bot|dashboard|service|project|framework|library)\b",
    re.IGNORECASE,
)
_CODE_SNIPPET_PATTERN = re.compile(
    r"\b(code\s+snippet|syntax|example\s+code|show\s+code|how\s+to\s+write)\b",
    re.IGNORECASE,
)
_WEB_SEARCH_PATTERN = re.compile(
    r"\b(search\s+the\s+web|search\s+web|look\s+up|find\s+online|web\s+search|google)\b",
    re.IGNORECASE,
)
_LEARNING_TOPIC_SANITIZER = re.compile(
    r"^(?:about|for|on|to\s+learn)\s+",
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


def _is_explicit_single_task_request(message: str) -> bool:
    normalized = re.sub(r"\s+", " ", message.strip())
    return bool(_CREATE_TASK_PATTERN.match(normalized))


def _extract_build_goal(message: str) -> str | None:
    normalized = re.sub(r"\s+", " ", message.strip())
    if not normalized:
        return None

    for pattern in _BUILD_APP_INTENT_PATTERNS:
        match = pattern.match(normalized)
        if not match:
            continue
        goal = str(match.group("goal") or "").strip(" .:-")
        goal = re.sub(r"^(?:building|making|creating|developing)\s+", "", goal, flags=re.IGNORECASE)
        if not goal:
            continue
        if not _APP_NOUN_PATTERN.search(goal) and "flask" not in goal.lower() and "django" not in goal.lower():
            continue
        return goal[:160]

    if _APP_NOUN_PATTERN.search(normalized) and re.search(r"\b(build|make|create|develop)\b", normalized, re.IGNORECASE):
        goal = re.sub(r"^(?:how\s+do\s+i\s+|how\s+to\s+)", "", normalized, flags=re.IGNORECASE)
        goal = re.sub(r"^(?:build|make|create|develop)\s+", "", goal, flags=re.IGNORECASE).strip(" .:-")
        return goal[:160] if goal else None

    return None


def _build_subtasks_for_goal(goal: str) -> list[str]:
    stack_hints: list[str] = []
    lowered = goal.lower()
    for token in ("python", "flask", "django", "javascript", "react", "sqlite", "postgres"):
        if token in lowered:
            stack_hints.append(token)

    stack_suffix = f" using {' + '.join(stack_hints)}" if stack_hints else ""
    return [
        f"Define a minimal feature scope for {goal}",
        f"Set up the project structure and dependencies{stack_suffix}",
        f"Implement the core functionality for {goal}",
        "Add tests and validate the main user flow end-to-end",
        "Prepare deployment/run instructions and polish documentation",
    ]


def _normalize_learning_difficulties(profile: dict[str, Any] | None) -> list[str]:
    if not isinstance(profile, dict):
        return []

    raw = profile.get("learning_difficulties", [])
    if isinstance(raw, str):
        values = [item.strip().lower() for item in raw.split(",") if item.strip()]
    elif isinstance(raw, list):
        values = [str(item).strip().lower() for item in raw if str(item).strip()]
    else:
        values = []

    return [item for item in values if item and item != "none"]


def _build_learning_support_hints(profile: dict[str, Any] | None) -> list[str]:
    difficulties = set(_normalize_learning_difficulties(profile))
    hints: list[str] = []

    if "dyslexia" in difficulties:
        hints.append("Prefer short bullet-based notes and plain wording for each step")
    if "adhd" in difficulties or "executive_function" in difficulties:
        hints.append("Keep milestones small and time-boxed so momentum is easier to maintain")
    if "visual_processing" in difficulties:
        hints.append("Use high-contrast labels and avoid crowded checklists")
    if "auditory_processing" in difficulties:
        hints.append("Keep written instructions explicit instead of relying on verbal memory")
    if "memory" in difficulties:
        hints.append("Repeat key decisions in task notes to reduce context switching")

    return hints


def _build_project_task_breakdown(goal: str, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    clean_goal = str(goal or "Project").strip(" .:-") or "Project"
    panel_name = clean_goal[:80]
    if not panel_name.lower().endswith("project"):
        panel_name = f"{panel_name} Project"

    programming_knowledge = ""
    if isinstance(profile, dict):
        programming_knowledge = str(profile.get("programming_knowledge") or "").strip()
    support_hints = _build_learning_support_hints(profile)
    support_suffix = f" Accessibility support: {'; '.join(support_hints[:2])}." if support_hints else ""
    readiness_suffix = (
        f" Skill baseline reported as {programming_knowledge}."
        if programming_knowledge and programming_knowledge.lower() != "none"
        else ""
    )

    return {
        "list_name": panel_name[:80],
        "tasks": [
            {
                "title": f"Define the outcome for {clean_goal}",
                "notes": (
                    "Why this task is necessary: a clear outcome keeps the project focused and prevents"
                    f" unplanned scope growth.{readiness_suffix}{support_suffix}"
                )[:300],
                "subtasks": [
                    "Write one sentence describing the user problem this project solves - this anchors all later decisions.",
                    "List 3 to 5 must-have features for the first version - this protects delivery scope.",
                    "List explicit non-goals - this prevents distractions and uncontrolled backlog growth.",
                ],
            },
            {
                "title": "Set up the build foundation",
                "notes": (
                    "Why this task is necessary: stable project setup prevents environment issues from blocking"
                    " implementation work."
                )[:300],
                "subtasks": [
                    "Create project structure and dependency list - this ensures repeatable onboarding and setup.",
                    "Configure formatting/linting/testing checks - this catches defects earlier.",
                    "Run a first smoke workflow - this verifies the base stack works before feature work starts.",
                ],
            },
            {
                "title": "Implement a first end-to-end feature slice",
                "notes": (
                    "Why this task is necessary: shipping one complete slice quickly validates architecture"
                    " and user flow assumptions."
                )[:300],
                "subtasks": [
                    "Build one user flow from input to output - this proves the system can deliver value.",
                    "Add validation and error states - this prevents fragile user experiences.",
                    "Capture short design notes - this preserves context for future iterations.",
                ],
            },
            {
                "title": "Harden quality and delivery readiness",
                "notes": (
                    "Why this task is necessary: testing and release prep reduce regressions and make handoff"
                    " easier for future sessions."
                )[:300],
                "subtasks": [
                    "Add tests for the main user path - this protects critical behavior during refactors.",
                    "Write run/deploy instructions - this lowers setup friction for future work.",
                    "Plan the next milestone and review blockers - this keeps progress predictable.",
                ],
            },
        ],
    }


def _extract_learning_topic(message: str) -> str | None:
    normalized = re.sub(r"\s+", " ", message.strip())
    if not normalized:
        return None

    for pattern in _LEARNING_PLAN_PATTERNS:
        match = pattern.match(normalized)
        if not match:
            continue
        topic = str(match.group("topic") or "").strip(" .:-")
        topic = _LEARNING_TOPIC_SANITIZER.sub("", topic).strip(" .:-")
        if topic:
            return topic[:120]
    return None


def _build_learning_subtasks(topic: str) -> list[str]:
    return [
        f"Define a clear learning goal for {topic}",
        f"Set up a practice environment and starter resources for {topic}",
        f"Learn core fundamentals of {topic} with short focused drills",
        f"Build a mini project that applies {topic}",
        f"Review gaps, document key takeaways, and plan the next milestone for {topic}",
    ]


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
    profile: dict[str, Any] | None = None,
    allow_web_search: bool = False,
    feedback_context: dict[str, Any] | None = None,
    active_task: dict[str, Any] | None = None,
) -> dict[str, Any]:
    title = _extract_task_draft_title(message)
    build_goal = _extract_build_goal(message)
    learning_topic = _extract_learning_topic(message)

    active_list_name = "General"
    if isinstance(active_task, dict):
        active_list_name = str(active_task.get("list_name") or active_task.get("list") or "General").strip() or "General"

    if learning_topic:
        task_title = learning_topic if learning_topic.lower().startswith("learn ") else f"Learn {learning_topic}"
        return {
            "message": f"Created a learning plan task for: {learning_topic}",
            "action": "create_task",
            "start_new_session": True,
            "task": {
                "title": task_title[:160],
                "notes": "Generated from learning-plan request",
                "subtasks": _build_learning_subtasks(learning_topic),
                "list_name": active_list_name if active_list_name else "Learning Plans",
            },
        }

    if title:
        goal = build_goal or title
        project_like_request = (not _is_explicit_single_task_request(message)) and (
            bool(build_goal) or bool(_APP_NOUN_PATTERN.search(goal))
        )
        if project_like_request:
            project_plan = _build_project_task_breakdown(goal, profile=profile)
            return {
                "message": f"Created a project task panel for: {goal}",
                "action": "create_project_tasks",
                "project": project_plan,
            }
        subtasks = _build_subtasks_for_goal(goal) if build_goal else []
        return {
            "message": f"Created a task draft for: {title}",
            "action": "create_task",
            "task": {
                "title": title,
                "notes": "Created via chatbot fallback",
                "subtasks": subtasks,
                "list_name": active_list_name,
            },
        }

    if build_goal:
        project_plan = _build_project_task_breakdown(build_goal, profile=profile)
        return {
            "message": f"Created a project task panel for: {build_goal}",
            "action": "create_project_tasks",
            "project": project_plan,
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
    feedback = feedback_context or {}
    top_intents = feedback.get("chatbot", {}).get("top_intents", []) if isinstance(feedback, dict) else []
    intent_hint = ""
    if isinstance(top_intents, list) and top_intents:
        intent_hint = f" Recent learning patterns: {', '.join(str(tag) for tag in top_intents[:2])}."

    completion_hint = ""
    median_completion = feedback.get("tasks", {}).get("median_completion_minutes") if isinstance(feedback, dict) else None
    if isinstance(median_completion, (int, float)):
        completion_hint = (
            f" Typical completion pace is about {median_completion:.1f} minutes, "
            "so I can suggest chunk sizes that match your rhythm."
        )

    return {
        "message": (
            "I can help create tasks. Try: 'create task: Build API auth layer' or "
            "'set up tasks for capstone backend project'. "
            "I can also answer CS/project questions and share syntax snippets. "
            "For non-project topics, I can search the web with your permission. "
            f"Recent tasks: {recent_titles}.{intent_hint}"
            f"{completion_hint}"
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
    feedback_context: dict[str, Any] | None = None,
    active_task: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fallback = _fallback_response(
        message,
        tasks,
        profile=profile,
        allow_web_search=allow_web_search,
        feedback_context=feedback_context,
        active_task=active_task,
    )

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
        "message (string), action ('none' or 'create_task' or 'create_project_tasks' or 'request_web_permission' or 'web_search_results'), "
        "task (object when action=create_task), project (object when action=create_project_tasks). "
        "If action=create_task include task.title, task.notes, task.subtasks (array of strings), "
        "task.list_name. If action=create_project_tasks include project.list_name and project.tasks; "
        "each project task must include title, notes, and subtasks (3-5 strings). Keep concise.\n"
        "\n"
        "CRITICAL CONSTRAINT: When the user requests help with a project, application, learning topic, or asks "
        "'help me [verb] [noun]' (e.g., 'help me make a web app', 'help me learn Python', 'help me build an API'), "
        "you MUST create practical steps. For project/application requests use action=create_project_tasks with 4-6 "
        "project tasks, and each project task must include 3-5 subtasks. Learning requests can still use create_task. "
        "Do NOT generate tasks without subtasks in these cases.\n"
        "\n"
        "Task generation rules:\n"
        "- 'help me build/make/create an app/website/API/game' → create_project_tasks with practical breakdown\n"
        "- 'help me learn [topic]' → create_task with learning plan subtasks\n"
        "- 'help me set up [project]' → create_project_tasks with setup/bootstrap subtasks\n"
        "- Brief requests like 'Build a todo app', 'Make a chatbot' → create_project_tasks with subtasks\n"
        "- Requests asking for help or guidance on projects → ALWAYS generate subtasks and explain why each task matters\n"
        "- Respect user profile and learning_difficulties by adapting chunk size and instruction style in notes\n"
        "\n"
        "For CS/project questions without explicit help/build intent, provide clear conceptual help and short syntax examples.\n"
        "For unrelated topics, ask web-search permission before browsing.\n"
        "Use the analytics feedback signals to tune response style and planning granularity.\n"
        f"User message: {message}\n"
        f"Task history: {json.dumps(task_preview)}\n"
        f"Active task context: {json.dumps(active_task or {})}\n"
        f"Analytics feedback signals: {json.dumps(feedback_context or {})}\n"
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


def _normalize_project_payload(raw_project: Any) -> dict[str, Any] | None:
    if not isinstance(raw_project, dict):
        return None

    list_name = str(raw_project.get("list_name", "")).strip()
    tasks = _normalize_plan_tasks(raw_project.get("tasks"))
    if not list_name or not tasks:
        return None

    return {"list_name": list_name[:80], "tasks": tasks}


def _fallback_project_plan(
    profile: dict[str, Any],
    past_projects: list[dict[str, Any]],
    feedback_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    project_name = str(profile.get("project_name") or "Custom Project").strip() or "Custom Project"
    project_type = str(profile.get("project_type") or "web").strip() or "web"
    experience_level = str(profile.get("experience_level") or "beginner").strip() or "beginner"
    language_framework = str(profile.get("language_framework") or "").strip() or "stack not specified"
    time_management_style = str(profile.get("time_management_style") or "structured").strip()
    memory_style = str(profile.get("memory_style") or "mixed").strip()

    prior_names = ", ".join(item.get("name", "") for item in past_projects[:3] if item.get("name"))
    prior_context = prior_names or "none logged yet"

    completion_note = ""
    if isinstance(feedback_context, dict):
        median_minutes = feedback_context.get("tasks", {}).get("median_completion_minutes")
        if isinstance(median_minutes, (int, float)):
            completion_note = (
                f" Recent completion median is {median_minutes:.1f} minutes; "
                "prioritize milestone chunks close to that duration."
            )

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
                "notes": (
                    f"Use a {time_management_style} planning rhythm with milestones sized for weekly delivery."
                    f"{completion_note}"
                ),
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
    feedback_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fallback = _fallback_project_plan(profile, past_projects, feedback_context=feedback_context)
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
        f"\nFeedback signals: {json.dumps(feedback_context or {})}"
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


