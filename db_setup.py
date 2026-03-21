import argparse
import os
import re
import sqlite3
from getpass import getpass
from pathlib import Path
from typing import Optional

from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "data" / "neuroflow.db"
SCHEMA_PATH = BASE_DIR / "schema.sql"
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,50}$")


def _resolve_db_path(db_path: Optional[str] = None) -> Path:
    configured = db_path or os.getenv("NEUROFLOW_DB_PATH")
    return Path(configured) if configured else DEFAULT_DB_PATH


def _connect(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = _resolve_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_database(db_path: Optional[str] = None) -> None:
    conn = _connect(db_path)
    try:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as schema_file:
            conn.executescript(schema_file.read())
        conn.commit()
    finally:
        conn.close()


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
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, password_hash),
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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Initialize NeuroFlow auth database")
    parser.add_argument("--db-path", default=None, help="Override SQLite database path")
    parser.add_argument("--create-user", default=None, help="Username to create")
    return parser


if __name__ == "__main__":
    args = _build_parser().parse_args()
    initialize_database(args.db_path)
    print("Database initialized.")

    if args.create_user:
        password = getpass("Password (min 8 chars): ")
        if create_user(args.create_user, password, args.db_path):
            print("User created successfully.")
        else:
            print("User creation failed. Check username/password rules or duplicate username.")

