import argparse
import json
import logging
import os
import re
import sqlite3
from getpass import getpass
from pathlib import Path
from typing import Any
from typing import Optional

from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "data" / "neuroflow.db"
SCHEMA_PATH = BASE_DIR / "schema.sql"
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,50}$")
logger = logging.getLogger(__name__)


def _resolve_db_path(db_path: Optional[str] = None, mode: Optional[str] = None) -> Path:
    configured = db_path or os.getenv("NEUROFLOW_DB_PATH")
    if configured:
        return Path(configured)


    return DEFAULT_DB_PATH


def _connect(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = _resolve_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_database(db_path: Optional[str] = None) -> None:
    path = _resolve_db_path(db_path)

    def _apply_schema() -> None:
        conn = _connect(str(path))
        try:
            with open(SCHEMA_PATH, "r", encoding="utf-8") as schema_file:
                conn.executescript(schema_file.read())
            conn.commit()
        finally:
            conn.close()

    try:
        _apply_schema()
        conn = _connect(str(path))
        try:
            existing_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()
            }
            onboarding_columns = {
                "onboarding_required": "INTEGER NOT NULL DEFAULT 0",
                "onboarding_completed_at": "TEXT",
                "onboarding_data_json": "TEXT NOT NULL DEFAULT '{}'",
            }
            for column_name, column_definition in onboarding_columns.items():
                if column_name not in existing_columns:
                    conn.execute(f"ALTER TABLE users ADD COLUMN {column_name} {column_definition}")
            conn.commit()
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        # Recover automatically when the existing file is not a valid SQLite DB.
        if "not a database" not in str(exc).lower() or not path.exists():
            raise

        backup_path = path.with_name(f"{path.name}.corrupt")
        counter = 1
        while backup_path.exists():
            backup_path = path.with_name(f"{path.name}.corrupt.{counter}")
            counter += 1

        logger.warning(
            "Detected invalid SQLite file at %s. Backing it up to %s and recreating.",
            path,
            backup_path,
        )
        path.rename(backup_path)
        _apply_schema()


def _validate_username(username: str) -> bool:
    return bool(USERNAME_PATTERN.fullmatch(username or ""))


def create_user(username: str, password: str, db_path: Optional[str] = None) -> bool:
    if not _validate_username(username) or len(password) < 8:
        return False

    password_hash = generate_password_hash(password)

    try:
        conn = _connect(db_path)
        try:
            conn.execute(
                "INSERT INTO users (username, password_hash, onboarding_required, onboarding_data_json) VALUES (?, ?, ?, ?)",
                (username, password_hash, 1, json.dumps({})),
            )
            conn.commit()
        finally:
            conn.close()
        return True
    except sqlite3.IntegrityError:
        return False


def verify_user(username: str, password: str, db_path: Optional[str] = None):
    if not _validate_username(username) or not password:
        return None

    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT id, username, password_hash FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    finally:
        conn.close()

    if not row or not check_password_hash(row["password_hash"], password):
        return None

    return {"id": row["id"], "username": row["username"]}


def get_user_onboarding(user_id: int, db_path: Optional[str] = None) -> dict[str, Any] | None:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT onboarding_required, onboarding_completed_at, onboarding_data_json
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return None

    try:
        onboarding_data = json.loads(row["onboarding_data_json"] or "{}")
    except json.JSONDecodeError:
        onboarding_data = {}

    if not isinstance(onboarding_data, dict):
        onboarding_data = {}

    return {
        "required": bool(row["onboarding_required"]),
        "completed_at": row["onboarding_completed_at"],
        "data": onboarding_data,
    }


def save_user_onboarding(user_id: int, payload: dict[str, object], db_path: Optional[str] = None) -> dict[str, Any]:
    programming_knowledge = str(payload.get("programming_knowledge", "")).strip()
    has_project_experience_raw = payload.get("has_project_experience", False)
    if isinstance(has_project_experience_raw, str):
        has_project_experience = has_project_experience_raw.strip().lower() in {"1", "true", "yes", "on"}
    else:
        has_project_experience = bool(has_project_experience_raw)

    project_examples = str(payload.get("project_examples", "")).strip()
    learning_difficulties_raw = payload.get("learning_difficulties", [])
    if isinstance(learning_difficulties_raw, str):
        learning_difficulties = [item.strip() for item in learning_difficulties_raw.split(",") if item.strip()]
    elif isinstance(learning_difficulties_raw, list):
        learning_difficulties = [str(item).strip() for item in learning_difficulties_raw if str(item).strip()]
    else:
        learning_difficulties = []

    onboarding_data = {
        "programming_knowledge": programming_knowledge,
        "has_project_experience": has_project_experience,
        "project_examples": project_examples,
        "learning_difficulties": learning_difficulties,
    }

    conn = _connect(db_path)
    try:
        cursor = conn.execute(
            """
            UPDATE users
            SET onboarding_required = 0,
                onboarding_completed_at = CURRENT_TIMESTAMP,
                onboarding_data_json = ?
            WHERE id = ?
            """,
            (json.dumps(onboarding_data), user_id),
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise ValueError("User not found")
    finally:
        conn.close()

    return onboarding_data


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Initialize NeuroFlow auth database")
    parser.add_argument("--db-path", default=None, help="Override SQLite database path")
    parser.add_argument("--create-user", default=None, help="Username to create")
    parser.add_argument(
        "--mode",
        choices=["dev", "web", "desktop"],
        default=None,
        help="Runtime mode used to choose default DB path when --db-path is not provided.",
    )
    return parser


if __name__ == "__main__":
    args = _build_parser().parse_args()
    resolved_db_path = _resolve_db_path(args.db_path, args.mode)
    initialize_database(str(resolved_db_path))
    print(f"Database initialized at {resolved_db_path}.")

    if args.create_user:
        password = getpass("Password (min 8 chars): ")
        if create_user(args.create_user, password, str(resolved_db_path)):
            print("User created successfully.")
        else:
            print("User creation failed. Check username/password rules or duplicate username.")

