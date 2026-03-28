"""
NeuroFlow Flask application factory and route handlers.

Provides the create_app factory function for instantiating Flask apps in different modes,
plus centralized route registration and security middleware.
"""

import logging
import secrets
from typing import Optional

from flask import Flask, flash, redirect, render_template, request, session, url_for

from src.config import BASE_DIR, load_runtime_config
from src.constants import (
    CSRF_TOKEN_LENGTH,
    SECURITY_HEADERS,
    SESSION_CONFIG,
)
from src.logging_config import setup_logger
from src.services.db_setup import initialize_database, verify_user

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
    )

    if init_db:
        try:
            initialize_database(runtime.db_path)
            logger.info(f"Database initialized at {runtime.db_path}")
        except Exception as exc:
            logger.error(f"Failed to initialize database: {exc}", exc_info=True)
            raise RuntimeError(f"Database initialization failed: {exc}") from exc

    register_security_headers(app)
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
    token = session.get("csrf_token")
    posted = request.form.get("csrf_token", "")
    return bool(token and posted and secrets.compare_digest(token, posted))


def register_routes(app: Flask) -> None:
    """Register Flask route handlers."""
    @app.route("/health", methods=["GET"])
    def health() -> tuple[dict[str, str], int]:
        """Container liveness/readiness endpoint."""
        return {"status": "ok"}, 200

    @app.route("/")
    def dashboard():
        """Dashboard view (protected by login)."""
        if "user_id" not in session:
            return redirect(url_for("login"))
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
                return redirect(url_for("dashboard"))
            else:
                logger.warning(f"Failed login attempt for username: {username}")
                flash("Invalid username or password.", "error")

        return render_template("Login.html", csrf_token=_ensure_csrf_token())

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

