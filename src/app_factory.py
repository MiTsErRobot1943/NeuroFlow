"""
NeuroFlow Flask application factory and route handlers.

Provides the create_app factory function for instantiating Flask apps in different modes,
plus centralized route registration and security middleware.
"""

import secrets
import hashlib
import re
from src.services import task_store as task_store_service
from datetime import date, datetime, timedelta
from typing import Optional

from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for

from src.config import BASE_DIR, load_runtime_config
from src.constants import (
    CSRF_TOKEN_LENGTH,
    SECURITY_HEADERS,
    SESSION_CONFIG,
)
from src.logging_config import setup_logger
from src.services.analytics_store import initialize_analytics_database
from src.services.analytics_store import get_user_feedback_context
from src.services.analytics_store import list_recent_projects
from src.services.analytics_store import track_event
from src.services.chatbot import generate_project_plan
from src.services.chatbot import generate_response
from src.services.db_setup import create_user, initialize_database, verify_user
from src.services.db_setup import get_user_onboarding
from src.services.db_setup import save_user_onboarding
from src.services.task_store import add_subtask
from src.services.task_store import append_chat_message
from src.services.task_store import create_task
from src.services.task_store import create_task_list
from src.services.task_store import delete_task
from src.services.task_store import list_chat_history
from src.services.task_store import list_task_lists
from src.services.task_store import list_tasks
from src.services.task_store import save_project_profile
from src.services.task_store import set_subtask_done
from src.services.task_store import set_task_done

logger = setup_logger(__name__)


def create_app(mode: Optional[str] = None, init_db: bool = True) -> Flask:
    """
    Create and configure a Flask application for the specified runtime mode.

    Args:
        mode: Runtime mode ('dev', 'web', 'desktop'). Defaults to environment or 'dev'.
        init_db: Whether to initialize the database schema on startup. Default: True.

    Returns:
        Configured Flask application instance.

    Raises:
        RuntimeError: If database initialization fails.
    """
    runtime = load_runtime_config(mode)
    logger.info(f"Creating Flask app in '{runtime.mode}' mode")

    app = Flask(
        __name__,
        template_folder=str(BASE_DIR / "src" / "assets" / "templates"),
        static_folder=str(BASE_DIR / "src" / "assets" / "templates"),
        static_url_path="/static",
    )
    app.config.update(
        SECRET_KEY=runtime.secret_key,
        SESSION_COOKIE_HTTPONLY=SESSION_CONFIG["COOKIE_HTTPONLY"],
        SESSION_COOKIE_SAMESITE=SESSION_CONFIG["COOKIE_SAMESITE"],
        NEUROFLOW_MODE=runtime.mode,
        NEUROFLOW_DB_PATH=str(runtime.db_path),
        ANALYTICS_DATABASE_URL=runtime.analytics_database_url or "",
    )

    if init_db:
        try:
            initialize_database(str(runtime.db_path))
            logger.info(f"Database initialized at {runtime.db_path}")
        except Exception as exc:
            logger.error(f"Failed to initialize database: {exc}", exc_info=True)
            raise RuntimeError(f"Database initialization failed: {exc}") from exc

    register_security_headers(app)
    initialize_analytics_database(runtime.analytics_database_url)
    register_routes(app)
    logger.info(f"Flask app ready on {runtime.host}:{runtime.port}")
    return app


def register_security_headers(app: Flask) -> None:
    """
    Register HTTP security headers as Flask after_request middleware.

    Args:
        app: Flask application instance
    """
    @app.after_request
    def set_security_headers(response):
        for header, value in SECURITY_HEADERS.items():
            response.headers[header] = value
        return response


def _ensure_csrf_token() -> str:
    """Ensure a CSRF token exists in session; create one if missing."""
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(CSRF_TOKEN_LENGTH)
        session["csrf_token"] = token
    return token


def _validate_csrf() -> bool:
    """Validate CSRF token from session against POST form data."""
    token = str(session.get("csrf_token") or "")
    payload = request.get_json(silent=True) if request.is_json else {}
    posted = str(request.form.get("csrf_token", "") or request.headers.get("X-CSRF-Token", ""))
    if not posted and isinstance(payload, dict):
        posted = str(payload.get("csrf_token", "") or "")
    return bool(token and posted and secrets.compare_digest(str(token), str(posted)))


def _json_error(message: str, status: int = 400):
    return jsonify({"ok": False, "error": message}), status


def _require_session_user():
    user_id = session.get("user_id")
    if not user_id:
        return None, _json_error("Authentication required", 401)
    return int(str(user_id)), None


def _get_onboarding_state(user_id: int, db_path: str) -> dict[str, object]:
    onboarding = get_user_onboarding(user_id, db_path)
    if onboarding is None:
        return {"required": False, "completed_at": None, "data": {}}
    return onboarding


def _onboarding_redirect_target(user_id: int, db_path: str) -> Optional[str]:
    onboarding = _get_onboarding_state(user_id, db_path)
    if onboarding.get("required"):
        return url_for("onboarding")
    return None


def _build_chatbot_profile(user_id: int, db_path: str, payload_profile: object) -> dict[str, object]:
    profile: dict[str, object] = {}
    if isinstance(payload_profile, dict):
        profile.update(payload_profile)

    onboarding_state = _get_onboarding_state(user_id, db_path)
    onboarding_data = onboarding_state.get("data") if isinstance(onboarding_state, dict) else {}
    if isinstance(onboarding_data, dict):
        if onboarding_data.get("programming_knowledge"):
            profile["programming_knowledge"] = onboarding_data.get("programming_knowledge")
        if isinstance(onboarding_data.get("learning_difficulties"), list):
            profile["learning_difficulties"] = onboarding_data.get("learning_difficulties")
        if "has_project_experience" in onboarding_data:
            profile["has_project_experience"] = onboarding_data.get("has_project_experience")
        if onboarding_data.get("project_examples"):
            profile["project_examples"] = onboarding_data.get("project_examples")

    latest_profile_fn = getattr(task_store_service, "get_latest_project_profile", None)
    latest_profile = latest_profile_fn(user_id, db_path) if callable(latest_profile_fn) else None
    if isinstance(latest_profile, dict):
        profile.update({k: v for k, v in latest_profile.items() if v not in (None, "")})
    return profile


def _require_completed_session(db_path: str):
    user_id, error = _require_session_user()
    if error:
        return None, error

    onboarding_target = _onboarding_redirect_target(user_id, db_path)
    if onboarding_target:
        return None, _json_error("Onboarding required", 403)

    return user_id, None


def _create_project_tasks_from_template(template_name: str) -> tuple[str, list[dict[str, object]]]:
    templates: dict[str, tuple[str, list[dict[str, object]]]] = {
        "web": (
            "Web Project",
            [
                {
                    "title": "Set up web project baseline",
                    "notes": "Initialize stack, linting, and CI checks.",
                    "subtasks": ["Create repository structure", "Set up environment config", "Run first smoke test"],
                },
                {
                    "title": "Implement authentication flow",
                    "notes": "Add login session, CSRF checks, and logout route.",
                    "subtasks": ["Design login form", "Validate credentials", "Add tests for auth flow"],
                },
                {
                    "title": "Build dashboard UI",
                    "notes": "Ship a responsive dashboard with task widgets.",
                    "subtasks": ["Create stat cards", "Wire API integration", "Review accessibility"],
                },
            ],
        ),
        "desktop": (
            "Desktop App",
            [
                {
                    "title": "Package desktop runtime",
                    "notes": "Ensure backend + pywebview launch reliably.",
                    "subtasks": ["Verify window startup", "Handle backend health checks", "Document build script"],
                },
                {
                    "title": "Desktop UX pass",
                    "notes": "Tune layout and interactions for desktop workflows.",
                    "subtasks": ["Review keyboard navigation", "Add offline-friendly messaging", "Polish error handling"],
                },
            ],
        ),
        "architecture": (
            "Software Architecture",
            [
                {
                    "title": "Define system boundaries",
                    "notes": "Clarify service responsibilities and data ownership.",
                    "subtasks": ["Draw context diagram", "List bounded modules", "Review failure cases"],
                },
                {
                    "title": "Write architecture decision records",
                    "notes": "Document key trade-offs for maintainability.",
                    "subtasks": ["Persistence strategy", "Deployment strategy", "Testing strategy"],
                },
            ],
        ),
        "database": (
            "Database Design",
            [
                {
                    "title": "Model relational schema",
                    "notes": "Design entities, relationships, and indexes.",
                    "subtasks": ["Define core tables", "Add constraints", "Plan migrations"],
                },
                {
                    "title": "Prepare analytics layer",
                    "notes": "Design event ingestion and reporting views.",
                    "subtasks": ["Define event taxonomy", "Create aggregation query", "Validate sample dashboard"],
                },
            ],
        ),
    }
    return templates.get(template_name, templates["web"])


def _normalize_iso_date(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return date.fromisoformat(text).isoformat()


def _plan_task_deadlines(task_defs: list[dict[str, object]], target_deadline: str | None) -> list[str | None]:
    if not task_defs:
        return []
    if not target_deadline:
        return [None for _ in task_defs]

    target = date.fromisoformat(target_deadline)
    today = date.today()
    total = len(task_defs)
    day_span = max((target - today).days, 0)

    if total == 1:
        return [target.isoformat()]

    scheduled: list[str] = []
    for index in range(total):
        offset = round(day_span * ((index + 1) / total))
        scheduled_date = today + timedelta(days=max(0, offset))
        if scheduled_date > target:
            scheduled_date = target
        scheduled.append(scheduled_date.isoformat())
    return scheduled


def _build_query_pattern_payload(message: str) -> dict[str, object]:
    normalized = re.sub(r"\s+", " ", message.strip())
    lowered = normalized.lower()
    tokens = [piece for piece in re.split(r"\W+", lowered) if piece]

    intent_tags: list[str] = []
    if any(word in lowered for word in ("create", "add", "task", "plan", "steps")):
        intent_tags.append("task_planning")
    if any(word in lowered for word in ("debug", "bug", "error", "fix", "traceback")):
        intent_tags.append("debugging")
    if any(word in lowered for word in ("how", "explain", "what", "why", "example")):
        intent_tags.append("learning")
    if any(word in lowered for word in ("search", "web", "google", "online")):
        intent_tags.append("web_lookup")
    if any(word in lowered for word in ("snippet", "syntax", "code")):
        intent_tags.append("code_snippet")

    fingerprint = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16] if normalized else ""
    return {
        "query_token_count": len(tokens),
        "query_char_count": len(normalized),
        "query_fingerprint": fingerprint,
        "intent_tags": intent_tags,
    }


def _parse_sqlite_timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    candidate = text.replace(" ", "T")
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        return None


def _completion_minutes_for_task(task: dict[str, object]) -> float | None:
    completed_at = _parse_sqlite_timestamp(task.get("updated_at"))
    created_at = _parse_sqlite_timestamp(task.get("created_at"))
    if not created_at or not completed_at:
        return None
    delta_minutes = (completed_at - created_at).total_seconds() / 60.0
    if delta_minutes < 0:
        return None
    return round(delta_minutes, 2)


def register_routes(app: Flask) -> None:
    """Register Flask route handlers."""
    @app.route("/health", methods=["GET"])
    def health() -> tuple[dict[str, str], int]:
        """Container liveness/readiness endpoint."""
        return {"status": "ok"}, 200

    @app.route("/")
    def dashboard():
        """Dashboard view (protected by login)."""
        user_id, error = _require_session_user()
        if error:
            return redirect(url_for("login"))

        onboarding_target = _onboarding_redirect_target(user_id, app.config["NEUROFLOW_DB_PATH"])
        if onboarding_target:
            return redirect(onboarding_target)

        return render_template(
            "Dashboard.html",
            username=session.get("username", "User"),
            csrf_token=_ensure_csrf_token(),
        )

    @app.route("/login", methods=["GET", "POST"])
    def login():
        """Login form and authentication handler."""
        if request.method == "POST":
            if not _validate_csrf():
                logger.warning("CSRF token validation failed for login attempt")
                flash("Invalid request token. Please try again.", "error")
                return redirect(url_for("login"))

            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")

            user = verify_user(
                username=username,
                password=password,
                db_path=app.config["NEUROFLOW_DB_PATH"],
            )

            if user:
                logger.info(f"Successful login for user: {user['username']}")
                session.clear()
                session["user_id"] = user["id"]
                session["username"] = user["username"]
                session["csrf_token"] = secrets.token_urlsafe(CSRF_TOKEN_LENGTH)
                track_event(
                    app.config.get("ANALYTICS_DATABASE_URL"),
                    "login_success",
                    user["username"],
                    {"mode": app.config.get("NEUROFLOW_MODE")},
                )

                onboarding_target = _onboarding_redirect_target(user["id"], app.config["NEUROFLOW_DB_PATH"])
                if onboarding_target:
                    return redirect(onboarding_target)
                return redirect(url_for("dashboard"))
            else:
                logger.warning(f"Failed login attempt for username: {username}")
                flash("Invalid username or password.", "error")

        return render_template("Login.html", csrf_token=_ensure_csrf_token())

    @app.route("/signup", methods=["GET", "POST"])
    def signup():
        """Sign-up form and account creation handler."""
        if "user_id" in session:
            return redirect(url_for("dashboard"))

        if request.method == "POST":
            if not _validate_csrf():
                logger.warning("CSRF token validation failed for signup attempt")
                flash("Invalid request token. Please try again.", "error")
                return redirect(url_for("signup"))

            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            confirm_password = request.form.get("confirm_password", "")

            if password != confirm_password:
                flash("Passwords do not match.", "error")
                return redirect(url_for("signup"))

            created = create_user(
                username=username,
                password=password,
                db_path=app.config["NEUROFLOW_DB_PATH"],
            )

            if created:
                logger.info(f"Successful signup for user: {username}")
                user = verify_user(username=username, password=password, db_path=app.config["NEUROFLOW_DB_PATH"])
                if user is None:
                    logger.error(f"verify_user returned None after successful create_user for username: {username}")
                    flash("Account created but could not be verified. Please log in.", "error")
                    return redirect(url_for("login"))
                session.clear()
                session["user_id"] = user["id"]
                session["username"] = user["username"]
                session["csrf_token"] = secrets.token_urlsafe(CSRF_TOKEN_LENGTH)
                track_event(
                    app.config.get("ANALYTICS_DATABASE_URL"),
                    "signup_success",
                    username,
                    {"mode": app.config.get("NEUROFLOW_MODE")},
                )
                flash("Account created successfully. Let’s finish your setup.", "success")
                return redirect(url_for("onboarding"))

            logger.warning(f"Failed signup attempt for username: {username}")
            flash("Unable to create account. Check username/password rules or duplicate username.", "error")

        return render_template("Signup.html", csrf_token=_ensure_csrf_token())

    @app.route("/onboarding", methods=["GET", "POST"])
    def onboarding():
        """Three-step onboarding wizard for new accounts."""
        user_id, error = _require_session_user()
        if error:
            return redirect(url_for("login"))

        onboarding_state = _get_onboarding_state(user_id, app.config["NEUROFLOW_DB_PATH"])
        if not onboarding_state.get("required"):
            return redirect(url_for("dashboard"))

        if request.method == "POST":
            if not _validate_csrf():
                logger.warning("CSRF token validation failed for onboarding submission")
                flash("Invalid request token. Please try again.", "error")
                return redirect(url_for("onboarding"))

            programming_knowledge = request.form.get("programming_knowledge", "").strip()
            has_project_experience = request.form.get("has_project_experience", "no").strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
            project_examples = request.form.get("project_examples", "").strip()
            learning_difficulties = [
                item.strip()
                for item in request.form.getlist("learning_difficulties")
                if item.strip()
            ]

            if has_project_experience and not project_examples:
                flash("Please tell us a little about the projects you have worked on.", "error")
                return redirect(url_for("onboarding"))

            onboarding_data = save_user_onboarding(
                user_id,
                {
                    "programming_knowledge": programming_knowledge,
                    "has_project_experience": has_project_experience,
                    "project_examples": project_examples,
                    "learning_difficulties": learning_difficulties,
                },
                app.config["NEUROFLOW_DB_PATH"],
            )

            track_event(
                app.config.get("ANALYTICS_DATABASE_URL"),
                "onboarding_completed",
                session.get("username", "user"),
                onboarding_data,
            )
            flash("Your preferences have been saved.", "success")
            return redirect(url_for("dashboard"))

        return render_template(
            "Onboarding.html",
            csrf_token=_ensure_csrf_token(),
            onboarding=onboarding_state.get("data", {}),
        )

    @app.route("/logout", methods=["POST"])
    def logout():
        """Logout handler (clears session)."""
        if not _validate_csrf():
            logger.warning("CSRF token validation failed for logout attempt")
            flash("Invalid request token.", "error")
            return redirect(url_for("dashboard"))

        logger.info(f"User session cleared for logout")
        session.clear()
        return redirect(url_for("login"))

    @app.route("/api/bootstrap", methods=["GET"])
    def api_bootstrap():
        user_id, error = _require_completed_session(app.config["NEUROFLOW_DB_PATH"])
        if error:
            return error

        db_path = app.config["NEUROFLOW_DB_PATH"]
        onboarding = _get_onboarding_state(user_id, db_path)
        return jsonify(
            {
                "ok": True,
                "username": session.get("username", "User"),
                "csrf_token": _ensure_csrf_token(),
                "onboarding": onboarding,
                "lists": list_task_lists(user_id, db_path),
                "tasks": list_tasks(user_id, db_path),
                "chat_history": list_chat_history(user_id, db_path),
            }
        )

    @app.route("/api/lists", methods=["POST"])
    def api_create_list():
        user_id, error = _require_completed_session(app.config["NEUROFLOW_DB_PATH"])
        if error:
            return error
        if not _validate_csrf():
            return _json_error("Invalid request token", 403)

        payload = request.get_json(silent=True) or {}
        name = str(payload.get("name", "")).strip()
        if not name:
            return _json_error("List name is required")

        created = create_task_list(user_id, name, app.config["NEUROFLOW_DB_PATH"])
        track_event(app.config.get("ANALYTICS_DATABASE_URL"), "list_created", session.get("username", "user"), created)
        return jsonify({"ok": True, "list": created})

    @app.route("/api/tasks", methods=["GET"])
    def api_list_tasks():
        user_id, error = _require_completed_session(app.config["NEUROFLOW_DB_PATH"])
        if error:
            return error
        db_path = app.config["NEUROFLOW_DB_PATH"]
        return jsonify(
            {
                "ok": True,
                "lists": list_task_lists(user_id, db_path),
                "tasks": list_tasks(user_id, db_path),
            }
        )

    @app.route("/api/tasks", methods=["POST"])
    def api_create_task():
        user_id, error = _require_completed_session(app.config["NEUROFLOW_DB_PATH"])
        if error:
            return error
        if not _validate_csrf():
            return _json_error("Invalid request token", 403)

        payload = request.get_json(silent=True) or {}
        title = str(payload.get("title", "")).strip()
        notes = str(payload.get("notes", "")).strip()
        list_id = payload.get("list_id")
        subtasks = payload.get("subtasks", [])
        source = str(payload.get("source", "manual"))
        due_date = payload.get("due_date")

        if not isinstance(subtasks, list):
            return _json_error("Subtasks must be an array")

        try:
            created = create_task(
                user_id=user_id,
                title=title,
                list_id=int(str(list_id)) if list_id not in (None, "") else None,
                notes=notes,
                subtasks=[str(item) for item in subtasks],
                db_path=app.config["NEUROFLOW_DB_PATH"],
                source=source,
                due_date=str(due_date).strip() if due_date not in (None, "") else None,
            )
        except ValueError as exc:
            return _json_error(str(exc), 400)
        track_event(app.config.get("ANALYTICS_DATABASE_URL"), "task_created", session.get("username", "user"), {"task_id": created["id"], "source": source})
        return jsonify({"ok": True, "task": created})

    @app.route("/api/tasks/<int:task_id>/done", methods=["POST"])
    def api_set_task_done(task_id: int):
        user_id, error = _require_completed_session(app.config["NEUROFLOW_DB_PATH"])
        if error:
            return error
        if not _validate_csrf():
            return _json_error("Invalid request token", 403)

        payload = request.get_json(silent=True) or {}
        task = set_task_done(user_id, task_id, bool(payload.get("done", False)), app.config["NEUROFLOW_DB_PATH"])

        track_event(
            app.config.get("ANALYTICS_DATABASE_URL"),
            "task_completion",
            session.get("username", "user"),
            {
                "task_id": task.get("id"),
                "done": bool(task.get("done", False)),
                "source": task.get("source", "manual"),
                "completion_minutes": _completion_minutes_for_task(task) if bool(task.get("done", False)) else None,
            },
        )
        return jsonify({"ok": True, "task": task})

    @app.route("/api/subtasks/<int:subtask_id>/done", methods=["POST"])
    def api_set_subtask_done(subtask_id: int):
        user_id, error = _require_completed_session(app.config["NEUROFLOW_DB_PATH"])
        if error:
            return error
        if not _validate_csrf():
            return _json_error("Invalid request token", 403)

        payload = request.get_json(silent=True) or {}
        task = set_subtask_done(user_id, subtask_id, bool(payload.get("done", False)), app.config["NEUROFLOW_DB_PATH"])
        track_event(
            app.config.get("ANALYTICS_DATABASE_URL"),
            "subtask_completion",
            session.get("username", "user"),
            {
                "subtask_id": subtask_id,
                "task_id": task.get("id"),
                "done": bool(payload.get("done", False)),
            },
        )
        return jsonify({"ok": True, "task": task})

    @app.route("/api/tasks/<int:task_id>/subtasks", methods=["POST"])
    def api_add_subtask(task_id: int):
        user_id, error = _require_completed_session(app.config["NEUROFLOW_DB_PATH"])
        if error:
            return error
        if not _validate_csrf():
            return _json_error("Invalid request token", 403)

        payload = request.get_json(silent=True) or {}
        title = str(payload.get("title", "")).strip()
        added = add_subtask(user_id, task_id, title, app.config["NEUROFLOW_DB_PATH"])
        return jsonify({"ok": True, "subtask": added})

    @app.route("/api/tasks/<int:task_id>", methods=["DELETE"])
    def api_delete_task(task_id: int):
        user_id, error = _require_completed_session(app.config["NEUROFLOW_DB_PATH"])
        if error:
            return error
        if not _validate_csrf():
            return _json_error("Invalid request token", 403)

        delete_task(user_id, task_id, app.config["NEUROFLOW_DB_PATH"])
        return jsonify({"ok": True})

    @app.route("/api/chatbot", methods=["POST"])
    def api_chatbot():
        user_id, error = _require_completed_session(app.config["NEUROFLOW_DB_PATH"])
        if error:
            return error
        if not _validate_csrf():
            return _json_error("Invalid request token", 403)

        payload = request.get_json(silent=True) or {}
        message = str(payload.get("message", "")).strip()
        if not message:
            return _json_error("Message is required")

        allow_web_search = bool(payload.get("allow_web_search", False))
        skip_user_log = bool(payload.get("skip_user_log", False))
        selected_task_id_raw = payload.get("selected_task_id")

        db_path = app.config["NEUROFLOW_DB_PATH"]
        if not skip_user_log:
            append_chat_message(user_id, "user", message, db_path)

        tasks_snapshot = list_tasks(user_id, db_path)
        selected_task = None
        try:
            selected_task_id = int(str(selected_task_id_raw)) if selected_task_id_raw not in (None, "") else None
        except ValueError:
            selected_task_id = None
        if selected_task_id is not None:
            selected_task = next((task for task in tasks_snapshot if int(task.get("id", 0)) == selected_task_id), None)

        profile = _build_chatbot_profile(user_id, db_path, payload.get("profile"))
        feedback_context = get_user_feedback_context(
            app.config.get("ANALYTICS_DATABASE_URL"),
            session.get("username", "user"),
        )
        chatbot_response = generate_response(
            message=message,
            tasks=tasks_snapshot,
            profile=profile,
            allow_web_search=allow_web_search,
            feedback_context=feedback_context,
            active_task=selected_task,
        )

        created_task = None
        created_tasks = []
        if chatbot_response.get("action") == "create_task":
            task_payload = chatbot_response.get("task") or {}
            list_name = str(task_payload.get("list_name", "General")).strip() or "General"
            selected_list = create_task_list(user_id, list_name, db_path)
            raw_task_subtasks = task_payload.get("subtasks")
            task_subtasks = [str(item) for item in raw_task_subtasks if str(item).strip()] if isinstance(raw_task_subtasks, list) else []
            created_task = create_task(
                user_id=user_id,
                title=str(task_payload.get("title", "New Task")).strip() or "New Task",
                list_id=int(selected_list["id"]),
                notes=str(task_payload.get("notes", "")).strip(),
                subtasks=task_subtasks,
                db_path=db_path,
                source="chatbot",
            )
            created_tasks = [created_task]
        elif chatbot_response.get("action") == "create_project_tasks":
            raw_project_payload = chatbot_response.get("project")
            project_payload: dict[str, object] = raw_project_payload if isinstance(raw_project_payload, dict) else {}
            list_name = str(project_payload.get("list_name") or "Project Plan").strip() or "Project Plan"
            selected_list = create_task_list(user_id, list_name, db_path)
            task_defs: list[dict[str, object]] = []
            raw_task_defs = project_payload.get("tasks")
            if isinstance(raw_task_defs, list):
                for raw_item in raw_task_defs:
                    if isinstance(raw_item, dict):
                        task_defs.append(raw_item)

            for item in task_defs:
                if not isinstance(item, dict):
                    continue
                raw_subtasks = item.get("subtasks")
                subtasks: list[str] = []
                if isinstance(raw_subtasks, list):
                    for raw_subtask in raw_subtasks:
                        clean_subtask = str(raw_subtask).strip()
                        if clean_subtask:
                            subtasks.append(clean_subtask)
                created_tasks.append(
                    create_task(
                        user_id=user_id,
                        title=str(item.get("title", "")).strip() or "Project milestone",
                        list_id=int(selected_list["id"]),
                        notes=str(item.get("notes", "")).strip(),
                        subtasks=subtasks,
                        db_path=db_path,
                        source="chatbot",
                    )
                )
            if created_tasks:
                created_task = created_tasks[0]

        assistant_message = str(chatbot_response.get("message", "I am ready to help with your tasks."))
        append_chat_message(user_id, "assistant", assistant_message, db_path)

        track_event(
            app.config.get("ANALYTICS_DATABASE_URL"),
            "chatbot_interaction",
            session.get("username", "user"),
            {
                "action": chatbot_response.get("action", "none"),
                "created_task": bool(created_task),
                "created_task_count": len(created_tasks),
                "allow_web_search": allow_web_search,
                **_build_query_pattern_payload(message),
            },
        )
        return jsonify({"ok": True, "response": chatbot_response, "created_task": created_task, "created_tasks": created_tasks})

    @app.route("/api/projects/predefined", methods=["POST"])
    def api_predefined_project_tasks():
        user_id, error = _require_completed_session(app.config["NEUROFLOW_DB_PATH"])
        if error:
            return error
        if not _validate_csrf():
            return _json_error("Invalid request token", 403)

        payload = request.get_json(silent=True) or {}
        template_name = str(payload.get("template", "web")).strip().lower()
        try:
            target_deadline = _normalize_iso_date(payload.get("target_deadline"))
        except ValueError:
            return _json_error("target_deadline must be in YYYY-MM-DD format", 400)
        list_name, task_defs = _create_project_tasks_from_template(template_name)
        planned_deadlines = _plan_task_deadlines(task_defs, target_deadline)

        db_path = app.config["NEUROFLOW_DB_PATH"]
        selected_list = create_task_list(user_id, list_name, db_path)
        created_tasks = []
        for item, planned_due_date in zip(task_defs, planned_deadlines):
            raw_subtasks = item.get("subtasks", [])
            if not isinstance(raw_subtasks, list):
                raw_subtasks = []
            created_tasks.append(
                create_task(
                    user_id=user_id,
                    title=str(item.get("title", "")).strip(),
                    list_id=int(selected_list["id"]),
                    notes=str(item.get("notes", "")).strip(),
                    subtasks=[str(sub) for sub in raw_subtasks],
                    db_path=db_path,
                    source=f"template:{template_name}",
                    due_date=planned_due_date,
                )
            )

        track_event(
            app.config.get("ANALYTICS_DATABASE_URL"),
            "predefined_project_generated",
            session.get("username", "user"),
            {
                "template": template_name,
                "project_name": list_name,
                "task_count": len(created_tasks),
                "target_deadline": target_deadline,
            },
        )

        return jsonify({"ok": True, "list": selected_list, "created_tasks": created_tasks})

    @app.route("/api/projects/configure", methods=["POST"])
    def api_configure_project():
        user_id, error = _require_completed_session(app.config["NEUROFLOW_DB_PATH"])
        if error:
            return error
        if not _validate_csrf():
            return _json_error("Invalid request token", 403)

        payload = request.get_json(silent=True) or {}
        try:
            profile = save_project_profile(user_id, payload, app.config["NEUROFLOW_DB_PATH"])
        except ValueError as exc:
            return _json_error(str(exc), 400)
        username = session.get("username", "user")
        past_projects = list_recent_projects(
            app.config.get("ANALYTICS_DATABASE_URL"),
            username,
            limit=6,
        )

        feedback_context = get_user_feedback_context(
            app.config.get("ANALYTICS_DATABASE_URL"),
            username,
        )
        generated_plan = generate_project_plan(profile, past_projects, feedback_context=feedback_context)

        db_path = app.config["NEUROFLOW_DB_PATH"]
        list_name = str(generated_plan.get("list_name") or profile.get("project_name") or "Untitled Project").strip()
        if not list_name:
            list_name = "Untitled Project"
        selected_list = create_task_list(user_id, list_name, db_path)

        created_tasks = []
        generated_tasks = [item for item in generated_plan.get("tasks", []) if isinstance(item, dict)]
        planned_deadlines = _plan_task_deadlines(generated_tasks, profile.get("target_deadline"))

        for item, planned_due_date in zip(generated_tasks, planned_deadlines):
            raw_subtasks = item.get("subtasks", []) if isinstance(item, dict) else []
            if not isinstance(raw_subtasks, list):
                raw_subtasks = []

            created_tasks.append(
                create_task(
                    user_id=user_id,
                    title=str(item.get("title", "")).strip() or "Plan milestone",
                    list_id=int(selected_list["id"]),
                    notes=str(item.get("notes", "")).strip(),
                    subtasks=[str(sub) for sub in raw_subtasks if str(sub).strip()],
                    db_path=db_path,
                    source="project-config-ai",
                    due_date=planned_due_date,
                )
            )

        track_event(
            app.config.get("ANALYTICS_DATABASE_URL"),
            "project_configured",
            username,
            {
                "project_name": profile.get("project_name", ""),
                "project_type": profile.get("project_type", ""),
                "experience_level": profile.get("experience_level", ""),
                "language_framework": profile.get("language_framework", ""),
                "target_deadline": profile.get("target_deadline", ""),
                "task_count": len(created_tasks),
            },
        )

        return jsonify(
            {
                "ok": True,
                "profile": profile,
                "past_projects": past_projects,
                "list": selected_list,
                "created_tasks": created_tasks,
            }
        )

