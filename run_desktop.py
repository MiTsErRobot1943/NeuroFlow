"""
NeuroFlow desktop mode launcher.

Starts the Flask backend with pywebview desktop window, or performs health checks.
"""

import argparse
import sys
from urllib.request import urlopen
from urllib.error import URLError

from src.desktop_launcher import launch_desktop
from src.desktop_launcher import start_desktop_backend
from src.desktop_launcher import stop_desktop_backend
from src.desktop_launcher import wait_for_backend
from src.logging_config import setup_logger

logger = setup_logger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser for desktop mode."""
    parser = argparse.ArgumentParser(description="Run NeuroFlow desktop mode")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument(
        "--no-window",
        action="store_true",
        help="Start backend only, run a health check, then stop.",
    )
    return parser


def _backend_health_check(host: str, port: int | None) -> str:
    """
    Start backend, verify readiness, and stop (health check mode).

    Args:
        host: Backend bind address
        port: Backend port (or None for auto-selection)

    Returns:
        Health check status message

    Raises:
        RuntimeError: If health check fails
    """
    backend = start_desktop_backend(host=host, port=port)
    url = f"http://{backend.host}:{backend.port}/login"

    try:
        wait_for_backend(url)
        with urlopen(url, timeout=2) as response:
            if response.status != 200:
                logger.error(f"Backend returned status {response.status}")
                raise RuntimeError(f"Unexpected status code: {response.status}")
        logger.info(f"Health check passed at {url}")
        return url
    except URLError as exc:
        logger.error(f"Health check failed: {exc}")
        raise RuntimeError(f"Health check failed: {exc}") from exc
    finally:
        stop_desktop_backend(backend)


def main() -> None:
    """CLI entrypoint for desktop mode."""
    args = _build_parser().parse_args()

    if args.no_window:
        try:
            url = _backend_health_check(args.host, args.port)
            print(f"Desktop backend startup smoke check passed at {url}")
        except Exception as exc:
            logger.error(f"Health check failed: {exc}", exc_info=True)
            sys.exit(1)
        return

    try:
        launch_desktop(host=args.host, port=args.port, with_window=True)
    except Exception as exc:
        logger.error(f"Desktop launch failed: {exc}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

