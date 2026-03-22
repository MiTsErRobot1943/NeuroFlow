"""
NeuroFlow security constants and utilities.

Centralized security configuration to prevent magic strings and improve maintainability.
"""

# ── Security Headers ──
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "script-src 'self'; "
        "img-src 'self' data:;"
    ),
}

# ── Session Configuration ──
SESSION_CONFIG = {
    "COOKIE_HTTPONLY": True,
    "COOKIE_SAMESITE": "Lax",
}

# ── Authentication Constants ──
MIN_PASSWORD_LENGTH = 8
USERNAME_PATTERN_STR = r"^[A-Za-z0-9_.-]{3,50}$"

# ── Desktop UI Constants ──
DESKTOP_WINDOW_WIDTH = 1280
DESKTOP_WINDOW_HEIGHT = 840
DESKTOP_WINDOW_TITLE = "NeuroFlow"

# ── Network Constants ──
LOCALHOST = "127.0.0.1"
DEFAULT_PORT = 5000
DEFAULT_HOST_WEB = "0.0.0.0"
DEFAULT_HOST_LOCAL = "127.0.0.1"

# ── Backend Startup Constants ──
BACKEND_READY_TIMEOUT = 10.0
BACKEND_READY_CHECK_INTERVAL = 0.1
BACKEND_SHUTDOWN_TIMEOUT = 2.0
HTTP_TIMEOUT = 1.0
HTTP_RESPONSE_OK = 200

# ── CSRF Token Constants ──
CSRF_TOKEN_LENGTH = 32  # secrets.token_urlsafe(32) produces ~43 chars

