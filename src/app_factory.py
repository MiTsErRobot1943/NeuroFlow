"""
NeuroFlow Flask application factory and route handlers.

Provides the create_app factory function for instantiating Flask apps in different modes,
plus centralized route registration and security middleware.
"""

import secrets
from typing import Optional
from typing import cast

from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for

from src.config import BASE_DIR, load_runtime_config
from src.constants import (
    CSRF_TOKEN_LENGTH,
    SECURITY_HEADERS,
    SESSION_CONFIG,
)
from src.logging_config import setup_logger
from src.services.analytics_store import initialize_analytics_database
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
        template_folder=str(BASE_DIR / "Template"),
        static_folder=str(BASE_DIR / "Template"),
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
                session.clear()
                if user:
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

        if not isinstance(subtasks, list):
            return _json_error("Subtasks must be an array")

        created = create_task(
            user_id=user_id,
            title=title,
            list_id=int(str(list_id)) if list_id not in (None, "") else None,
            notes=notes,
            subtasks=[str(item) for item in subtasks],
            db_path=app.config["NEUROFLOW_DB_PATH"],
            source=source,
        )
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

        db_path = app.config["NEUROFLOW_DB_PATH"]
        if not skip_user_log:
            append_chat_message(user_id, "user", message, db_path)

        tasks_snapshot = list_tasks(user_id, db_path)
        profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else None
        chatbot_response = generate_response(
            message=message,
            tasks=tasks_snapshot,
            profile=profile,
            allow_web_search=allow_web_search,
        )

        created_task = None
        if chatbot_response.get("action") == "create_task":
            task_payload = chatbot_response.get("task") or {}
            list_name = str(task_payload.get("list_name", "General")).strip() or "General"
            selected_list = create_task_list(user_id, list_name, db_path)
            created_task = create_task(
                user_id=user_id,
                title=str(task_payload.get("title", "New Task")).strip() or "New Task",
                list_id=int(selected_list["id"]),
                notes=str(task_payload.get("notes", "")).strip(),
                subtasks=[str(item) for item in task_payload.get("subtasks", []) if str(item).strip()],
                db_path=db_path,
                source="chatbot",
            )

        assistant_message = str(chatbot_response.get("message", "I am ready to help with your tasks."))
        append_chat_message(user_id, "assistant", assistant_message, db_path)

        track_event(
            app.config.get("ANALYTICS_DATABASE_URL"),
            "chatbot_interaction",
            session.get("username", "user"),
            {
                "action": chatbot_response.get("action", "none"),
                "created_task": bool(created_task),
                "allow_web_search": allow_web_search,
            },
        )
        return jsonify({"ok": True, "response": chatbot_response, "created_task": created_task})

    @app.route("/api/projects/predefined", methods=["POST"])
    def api_predefined_project_tasks():
        user_id, error = _require_completed_session(app.config["NEUROFLOW_DB_PATH"])
        if error:
            return error
        if not _validate_csrf():
            return _json_error("Invalid request token", 403)

        payload = request.get_json(silent=True) or {}
        template_name = str(payload.get("template", "web")).strip().lower()
        list_name, task_defs = _create_project_tasks_from_template(template_name)

        db_path = app.config["NEUROFLOW_DB_PATH"]
        selected_list = create_task_list(user_id, list_name, db_path)
        created_tasks = []
        for item in task_defs:
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
                )
            )

        track_event(
            app.config.get("ANALYTICS_DATABASE_URL"),
            "predefined_project_generated",
            session.get("username", "user"),
            {"template": template_name, "project_name": list_name, "task_count": len(created_tasks)},
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
        profile = save_project_profile(user_id, payload, app.config["NEUROFLOW_DB_PATH"])
        username = session.get("username", "user")
        past_projects = list_recent_projects(
            app.config.get("ANALYTICS_DATABASE_URL"),
            username,
            limit=6,
        )

        generated_plan = generate_project_plan(profile, past_projects)

        db_path = app.config["NEUROFLOW_DB_PATH"]
        list_name = str(generated_plan.get("list_name") or profile.get("project_name") or "Untitled Project").strip()
        if not list_name:
            list_name = "Untitled Project"
        selected_list = create_task_list(user_id, list_name, db_path)

        created_tasks = []
        for item in generated_plan.get("tasks", []):
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

