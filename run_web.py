"""
NeuroFlow web/server mode launcher.

Starts Flask development server or production-ready configuration per runtime mode.
"""

import argparse
import sys

from src.app_factory import create_app
from src.config import load_runtime_config
from src.logging_config import setup_logger

logger = setup_logger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser for web mode."""
    parser = argparse.ArgumentParser(description="Run NeuroFlow in web/server mode")
    parser.add_argument("--mode", choices=["dev", "web"], default="dev")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    return parser


def main() -> None:
    """CLI entrypoint for web mode."""
    args = _build_parser().parse_args()

    try:
        runtime = load_runtime_config(args.mode)
    except Exception as exc:
        logger.error(f"Failed to load runtime config: {exc}", exc_info=True)
        sys.exit(1)

    try:
        app = create_app(mode=args.mode, init_db=True)
    except Exception as exc:
        logger.error(f"Failed to create Flask app: {exc}", exc_info=True)
        sys.exit(1)

    host = args.host or runtime.host
    port = args.port or runtime.port
    logger.info(f"Starting web server at {host}:{port} (debug={runtime.debug})")

    app.run(
        host=host,
        port=port,
        debug=runtime.debug,
    )


if __name__ == "__main__":
    main()

