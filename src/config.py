"""
NeuroFlow runtime configuration.

Handles mode-aware settings (dev/web/desktop), database paths, and server initialization parameters.
"""

import logging
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.logging_config import setup_logger

logger = setup_logger(__name__)

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = BASE_DIR / "data" / "neuroflow.db"


@dataclass(frozen=True)
class RuntimeConfig:
    """Immutable runtime configuration container."""
    
    mode: str
    secret_key: str
    db_path: Path
    host: str
    port: int
    debug: bool


def _desktop_data_dir() -> Path:
    """
    Determine the platform-appropriate desktop app data directory.

    Priority:
        1. %APPDATA% (Windows user profile roaming)
        2. %LOCALAPPDATA% (Windows user profile local)
        3. Project data/ folder (fallback)

    Returns:
        Path to NeuroFlow desktop app data directory
    """
    appdata = os.getenv("APPDATA")
    if appdata:
        return Path(appdata) / "NeuroFlow"

    local_appdata = os.getenv("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata) / "NeuroFlow"

    return BASE_DIR / "data"


def _resolve_mode(mode: Optional[str] = None) -> str:
    """
    Resolve the runtime mode from argument, environment, or default.

    Valid modes: 'dev', 'web', 'desktop'

    Args:
        mode: Explicit mode string. If None, falls back to NEUROFLOW_MODE env var or 'dev'.

    Returns:
        Resolved mode string (one of: dev, web, desktop)
    """
    selected = (mode or os.getenv("NEUROFLOW_MODE") or "dev").strip().lower()

    if selected not in {"dev", "web", "desktop"}:
        logger.warning(
            f"Invalid runtime mode '{selected}' requested; defaulting to 'dev'. "
            f"Valid modes: dev, web, desktop"
        )
        return "dev"

    return selected


def load_runtime_config(mode: Optional[str] = None) -> RuntimeConfig:
    """
    Load runtime configuration based on mode and environment variables.

    Environment variables:
        - NEUROFLOW_MODE: Runtime mode (dev/web/desktop)
        - NEUROFLOW_DB_PATH: Override SQLite database path
        - NEUROFLOW_SECRET_KEY: Override Flask secret key
        - PORT: Override server port (default: 5000)

    Args:
        mode: Explicit runtime mode. If None, uses environment or defaults to 'dev'.

    Returns:
        RuntimeConfig instance with resolved settings
    """
    resolved_mode = _resolve_mode(mode)

    configured_db = os.getenv("NEUROFLOW_DB_PATH")
    if configured_db:
        db_path = Path(configured_db)
        logger.debug(f"Using configured DB path: {db_path}")
    else:
        db_path = DEFAULT_DB_PATH
        logger.debug(f"Using shared default DB path: {db_path}")

    host = "0.0.0.0" if resolved_mode == "web" else "127.0.0.1"
    port = int(os.getenv("PORT", "5000"))
    debug = resolved_mode == "dev"
    secret_key = os.getenv("NEUROFLOW_SECRET_KEY", secrets.token_hex(32))

    logger.info(
        f"Loaded runtime config: mode={resolved_mode}, host={host}, port={port}, debug={debug}"
    )

    return RuntimeConfig(
        mode=resolved_mode,
        secret_key=secret_key,
        db_path=db_path,
        host=host,
        port=port,
        debug=debug,
    )

