"""
NeuroFlow WSGI application entry point.

Provides compatibility layer for Gunicorn and container deployment.
Exports `app` object for: gunicorn app:app
"""

from src.app_factory import create_app
from src.config import load_runtime_config

# Kept for compatibility with tooling that imports app:app directly.
app = create_app(mode="web", init_db=False)


if __name__ == "__main__":
    runtime = load_runtime_config("dev")
    create_app(mode="dev", init_db=True).run(
        host=runtime.host,
        port=runtime.port,
        debug=runtime.debug,
    )
