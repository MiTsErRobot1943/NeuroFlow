"""
NeuroFlow desktop application launcher.

Provides backend startup, health checks, and pywebview window integration for desktop mode.
"""

import contextlib
import os
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional
from urllib.request import urlopen
from urllib.error import URLError

from werkzeug.serving import make_server

from src.app_factory import create_app
from src.constants import (
    BACKEND_READY_CHECK_INTERVAL,
    BACKEND_READY_TIMEOUT,
    BACKEND_SHUTDOWN_TIMEOUT,
    DESKTOP_WINDOW_HEIGHT,
    DESKTOP_WINDOW_TITLE,
    DESKTOP_WINDOW_WIDTH,
    HTTP_TIMEOUT,
)
from src.logging_config import setup_logger

logger = setup_logger(__name__)


def _configure_analytics_for_desktop() -> None:
    """
    Configure analytics database URL for desktop mode.
    
    Desktop mode connects to a local PostgreSQL instance at localhost:5432.
    Requires NEUROFLOW_ANALYTICS_DB_PASSWORD environment variable or uses default.
    Falls back gracefully if PostgreSQL is unavailable.
    """
    # Only configure if not already set
    if os.getenv("ANALYTICS_DATABASE_URL"):
        logger.debug("ANALYTICS_DATABASE_URL already set; skipping desktop analytics configuration")
        return
    
    # Build PostgreSQL connection string for local analytics database
    analytics_user = os.getenv("NEUROFLOW_ANALYTICS_USER", "neuroflow")
    analytics_password = os.getenv("NEUROFLOW_ANALYTICS_PASSWORD", "neuroflow")
    analytics_host = os.getenv("NEUROFLOW_ANALYTICS_HOST", "localhost")
    analytics_port = os.getenv("NEUROFLOW_ANALYTICS_PORT", "5432")
    analytics_db = os.getenv("NEUROFLOW_ANALYTICS_DB", "neuroflow_analytics")
    
    analytics_url = f"postgresql://{analytics_user}:{analytics_password}@{analytics_host}:{analytics_port}/{analytics_db}"
    
    # Set environment variable for Flask app to pick up
    os.environ["ANALYTICS_DATABASE_URL"] = analytics_url
    logger.info(f"Desktop analytics configured: {analytics_host}:{analytics_port}/{analytics_db}")



@dataclass
class DesktopBackend:
    """Container for desktop backend runtime state."""

    host: str
    port: int
    server: Any
    thread: threading.Thread


@contextlib.contextmanager
def _socket_bound_to_random_port(host: str):
    """Context manager yielding a socket bound to an available port."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((host, 0))
    try:
        yield sock
    finally:
        sock.close()


def _pick_open_port(host: str) -> int:
    """
    Find an available port on the specified host.

    Args:
        host: Host address (typically "127.0.0.1")

    Returns:
        Available port number
    """
    with _socket_bound_to_random_port(host) as sock:
        return sock.getsockname()[1]


def start_desktop_backend(
    host: str = "127.0.0.1",
    port: Optional[int] = None,
) -> DesktopBackend:
    """
    Start Flask backend in a daemon thread with werkzeug development server.

    Args:
        host: Bind address (default: "127.0.0.1")
        port: Port number. If None, auto-selects available port.

    Returns:
        DesktopBackend instance with running server and thread.

    Raises:
        RuntimeError: If server fails to start
    """
    selected_port = port or _pick_open_port(host)
    logger.info(f"Starting desktop backend on {host}:{selected_port}")

    # Configure analytics database for desktop mode
    _configure_analytics_for_desktop()

    try:
        app = create_app(mode="desktop", init_db=True)
    except Exception as exc:
        logger.error(f"Failed to create Flask app: {exc}", exc_info=True)
        raise RuntimeError(f"Failed to create Flask app: {exc}") from exc

    server = make_server(host, selected_port, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"Desktop backend thread started (port {selected_port})")

    return DesktopBackend(host=host, port=selected_port, server=server, thread=thread)


def stop_desktop_backend(backend: DesktopBackend) -> None:
    """
    Gracefully shut down desktop backend server and thread.

    Args:
        backend: DesktopBackend instance to stop
    """
    logger.info(f"Stopping desktop backend on {backend.host}:{backend.port}")
    backend.server.shutdown()
    backend.thread.join(timeout=BACKEND_SHUTDOWN_TIMEOUT)
    logger.info("Desktop backend stopped")


def wait_for_backend(url: str, timeout_seconds: float = 10.0) -> None:
    """
    Poll a URL until it responds with HTTP 200, with timeout.

    Args:
        url: URL to poll (typically http://127.0.0.1:PORT/login)
        timeout_seconds: Maximum time to wait before raising TimeoutError

    Raises:
        TimeoutError: If backend does not become ready within timeout
    """
    deadline = time.time() + timeout_seconds
    logger.info(f"Waiting for backend to be ready: {url} (timeout: {timeout_seconds}s)")

    while time.time() < deadline:
        try:
            with urlopen(url, timeout=HTTP_TIMEOUT):
                logger.info("Backend ready")
                return
        except (URLError, Exception) as exc:
            logger.debug(f"Backend not ready yet: {exc}")
            time.sleep(BACKEND_READY_CHECK_INTERVAL)

    raise TimeoutError(f"Backend did not become ready: {url}")


def launch_desktop(
    host: str = "127.0.0.1",
    port: Optional[int] = None,
    with_window: bool = True,
) -> str:
    """
    Launch NeuroFlow desktop application.

    Starts the Flask backend, waits for readiness, then opens a pywebview window.
    Automatically stops the backend when the window closes.

    Args:
        host: Backend bind address (default: "127.0.0.1")
        port: Backend port. If None, auto-selects available port.
        with_window: If False, starts backend and stops after health check.

    Returns:
        Application URL (http://host:port/login)

    Raises:
        RuntimeError: If pywebview is not installed or backend fails to start
    """
    backend = start_desktop_backend(host=host, port=port)
    app_url = f"http://{backend.host}:{backend.port}/login"

    try:
        wait_for_backend(app_url, timeout_seconds=BACKEND_READY_TIMEOUT)
    except TimeoutError as exc:
        stop_desktop_backend(backend)
        logger.error(f"Backend startup timeout: {exc}")
        raise

    if not with_window:
        stop_desktop_backend(backend)
        logger.info("Backend health check passed; stopping backend per --no-window flag")
        return app_url

    try:
        import webview
    except ImportError as exc:
        stop_desktop_backend(backend)
        logger.error("pywebview import failed")
        raise RuntimeError(
            "pywebview is not installed. Install with: pip install pywebview"
        ) from exc

    try:
        logger.info("Creating pywebview window")
        webview.create_window(
            DESKTOP_WINDOW_TITLE,
            app_url,
            width=DESKTOP_WINDOW_WIDTH,
            height=DESKTOP_WINDOW_HEIGHT,
        )
        logger.info("Starting pywebview event loop")
        webview.start(debug=False)
        logger.info("pywebview window closed; cleaning up")
    finally:
        stop_desktop_backend(backend)

    return app_url


