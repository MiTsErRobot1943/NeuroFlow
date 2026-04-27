"""SQLite-backed task, project profile, and chat history storage helpers."""

from __future__ import annotations

import datetime as dt
import sqlite3
from typing import Any


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _normalize_iso_date(value: str | None, field_name: str) -> str | None:
    clean_value = (value or "").strip()
    if not clean_value:
        return None
    try:
        return dt.date.fromisoformat(clean_value).isoformat()
    except ValueError as exc:
        raise ValueError(f"{field_name} must be in YYYY-MM-DD format") from exc


def ensure_default_list(user_id: int, db_path: str) -> dict[str, Any]:
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO task_lists (user_id, name) VALUES (?, ?)",
            (user_id, "General"),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id, name FROM task_lists WHERE user_id = ? AND name = ?",
            (user_id, "General"),
        ).fetchone()
        return {"id": row["id"], "name": row["name"]}
    finally:
        conn.close()


def list_task_lists(user_id: int, db_path: str) -> list[dict[str, Any]]:
    ensure_default_list(user_id, db_path)
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, name FROM task_lists WHERE user_id = ? ORDER BY created_at ASC, id ASC",
            (user_id,),
        ).fetchall()
        return [{"id": row["id"], "name": row["name"]} for row in rows]
    finally:
        conn.close()


def create_task_list(user_id: int, name: str, db_path: str) -> dict[str, Any]:
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("List name cannot be empty")

    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO task_lists (user_id, name) VALUES (?, ?)",
            (user_id, clean_name),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id, name FROM task_lists WHERE user_id = ? AND name = ?",
            (user_id, clean_name),
        ).fetchone()
        return {"id": row["id"], "name": row["name"]}
    finally:
        conn.close()


def _resolve_list_id(user_id: int, list_id: int | None, db_path: str) -> int:
    if list_id:
        conn = _connect(db_path)
        try:
            row = conn.execute(
                "SELECT id FROM task_lists WHERE id = ? AND user_id = ?",
                (list_id, user_id),
            ).fetchone()
            if row:
                return row["id"]
        finally:
            conn.close()

    return ensure_default_list(user_id, db_path)["id"]


def create_task(
    user_id: int,
    title: str,
    list_id: int | None,
    notes: str,
    subtasks: list[str],
    db_path: str,
    source: str = "manual",
    due_date: str | None = None,
) -> dict[str, Any]:
    clean_title = (title or "").strip()
    if not clean_title:
        raise ValueError("Task title cannot be empty")

    selected_list_id = _resolve_list_id(user_id, list_id, db_path)
    clean_subtasks = [item.strip() for item in subtasks if (item or "").strip()]
    normalized_due_date = _normalize_iso_date(due_date, "due_date")
    created_task_id = 0

    conn = _connect(db_path)
    try:
        cursor = conn.execute(
            """
            INSERT INTO tasks (user_id, list_id, title, notes, done, source, due_date)
            VALUES (?, ?, ?, ?, 0, ?, ?)
            """,
            (user_id, selected_list_id, clean_title, (notes or "").strip(), source, normalized_due_date),
        )
        created_task_id = int(cursor.lastrowid or 0)
        if created_task_id <= 0:
            raise RuntimeError("Failed to create task")

        for subtask_title in clean_subtasks:
            conn.execute(
                "INSERT INTO subtasks (task_id, title, done) VALUES (?, ?, 0)",
                (created_task_id, subtask_title),
            )

        conn.commit()
    finally:
        conn.close()

    if created_task_id <= 0:
        raise RuntimeError("Failed to create task")
    return get_task(user_id, created_task_id, db_path)


def get_task(user_id: int, task_id: int, db_path: str) -> dict[str, Any]:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT t.id, t.title, t.notes, t.done, t.list_id, t.source, t.due_date, t.created_at, t.updated_at, tl.name AS list_name
            FROM tasks t
            JOIN task_lists tl ON tl.id = t.list_id
            WHERE t.id = ? AND t.user_id = ?
            """,
            (task_id, user_id),
        ).fetchone()
        if not row:
            raise ValueError("Task not found")

        subtask_rows = conn.execute(
            "SELECT id, title, done FROM subtasks WHERE task_id = ? ORDER BY id ASC",
            (task_id,),
        ).fetchall()
        subtasks = [
            {"id": sub["id"], "title": sub["title"], "done": bool(sub["done"])}
            for sub in subtask_rows
        ]
        return {
            "id": row["id"],
            "title": row["title"],
            "notes": row["notes"],
            "done": bool(row["done"]),
            "list_id": row["list_id"],
            "list_name": row["list_name"],
            "source": row["source"],
            "due_date": row["due_date"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "subtasks": subtasks,
        }
    finally:
        conn.close()


def list_tasks(user_id: int, db_path: str) -> list[dict[str, Any]]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT t.id, t.title, t.notes, t.done, t.list_id, t.source, t.due_date, t.created_at, t.updated_at, tl.name AS list_name
            FROM tasks t
            JOIN task_lists tl ON tl.id = t.list_id
            WHERE t.user_id = ?
            ORDER BY t.id DESC
            """,
            (user_id,),
        ).fetchall()

        task_ids = [row["id"] for row in rows]
        subtasks_by_task: dict[int, list[dict[str, Any]]] = {task_id: [] for task_id in task_ids}

        if task_ids:
            placeholders = ",".join("?" for _ in task_ids)
            subtask_rows = conn.execute(
                f"SELECT id, task_id, title, done FROM subtasks WHERE task_id IN ({placeholders}) ORDER BY id ASC",
                task_ids,
            ).fetchall()
            for sub in subtask_rows:
                subtasks_by_task[sub["task_id"]].append(
                    {"id": sub["id"], "title": sub["title"], "done": bool(sub["done"])}
                )

        tasks: list[dict[str, Any]] = []
        for row in rows:
            tasks.append(
                {
                    "id": row["id"],
                    "title": row["title"],
                    "notes": row["notes"],
                    "done": bool(row["done"]),
                    "list_id": row["list_id"],
                    "list_name": row["list_name"],
                    "source": row["source"],
                    "due_date": row["due_date"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "subtasks": subtasks_by_task.get(row["id"], []),
                }
            )
        return tasks
    finally:
        conn.close()


def add_subtask(user_id: int, task_id: int, title: str, db_path: str) -> dict[str, Any]:
    clean_title = (title or "").strip()
    if not clean_title:
        raise ValueError("Subtask title cannot be empty")

    conn = _connect(db_path)
    try:
        task = conn.execute(
            "SELECT id FROM tasks WHERE id = ? AND user_id = ?",
            (task_id, user_id),
        ).fetchone()
        if not task:
            raise ValueError("Task not found")

        cursor = conn.execute(
            "INSERT INTO subtasks (task_id, title, done) VALUES (?, ?, 0)",
            (task_id, clean_title),
        )
        conn.commit()
        return {"id": cursor.lastrowid, "task_id": task_id, "title": clean_title, "done": False}
    finally:
        conn.close()


def set_task_done(user_id: int, task_id: int, done: bool, db_path: str) -> dict[str, Any]:
    conn = _connect(db_path)
    try:
        updated = conn.execute(
            """
            UPDATE tasks
            SET done = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND user_id = ?
            """,
            (1 if done else 0, task_id, user_id),
        )
        if updated.rowcount == 0:
            raise ValueError("Task not found")
        conn.commit()
    finally:
        conn.close()

    return get_task(user_id, task_id, db_path)


def set_subtask_done(user_id: int, subtask_id: int, done: bool, db_path: str) -> dict[str, Any]:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT s.task_id
            FROM subtasks s
            JOIN tasks t ON t.id = s.task_id
            WHERE s.id = ? AND t.user_id = ?
            """,
            (subtask_id, user_id),
        ).fetchone()
        if not row:
            raise ValueError("Subtask not found")

        conn.execute(
            "UPDATE subtasks SET done = ? WHERE id = ?",
            (1 if done else 0, subtask_id),
        )

        task_id = row["task_id"]
        totals = conn.execute(
            "SELECT COUNT(*) AS total, SUM(done) AS done_count FROM subtasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        total = totals["total"] or 0
        done_count = totals["done_count"] or 0
        auto_done = total > 0 and total == done_count
        conn.execute(
            "UPDATE tasks SET done = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (1 if auto_done else 0, task_id),
        )
        conn.commit()
    finally:
        conn.close()

    return get_task(user_id, task_id, db_path)


def delete_task(user_id: int, task_id: int, db_path: str) -> None:
    conn = _connect(db_path)
    try:
        deleted = conn.execute(
            "DELETE FROM tasks WHERE id = ? AND user_id = ?",
            (task_id, user_id),
        )
        if deleted.rowcount == 0:
            raise ValueError("Task not found")
        conn.commit()
    finally:
        conn.close()


def append_chat_message(user_id: int, role: str, message: str, db_path: str) -> None:
    clean_message = (message or "").strip()
    if not clean_message:
        return

    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO chat_history (user_id, role, message) VALUES (?, ?, ?)",
            (user_id, role, clean_message),
        )
        conn.commit()
    finally:
        conn.close()


def list_chat_history(user_id: int, db_path: str, limit: int = 30) -> list[dict[str, Any]]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT role, message, created_at
            FROM chat_history
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
        return [
            {"role": row["role"], "message": row["message"], "created_at": row["created_at"]}
            for row in reversed(rows)
        ]
    finally:
        conn.close()


def save_project_profile(user_id: int, payload: dict[str, str], db_path: str) -> dict[str, Any]:
    project_name = (payload.get("project_name") or "Untitled Project").strip()
    notes = (payload.get("notes") or "").strip()
    project_type = (payload.get("project_type") or "web").strip()
    experience_level = (payload.get("experience_level") or payload.get("web_experience") or "beginner").strip()
    language_framework = (payload.get("language_framework") or "").strip()
    time_management_style = (payload.get("time_management_style") or "structured").strip()
    memory_style = (payload.get("memory_style") or "mixed").strip()
    target_deadline = _normalize_iso_date(payload.get("target_deadline"), "target_deadline")

    web_exp = (payload.get("web_experience") or experience_level).strip()
    desktop_exp = (payload.get("desktop_experience") or experience_level).strip()
    architecture_exp = (payload.get("architecture_experience") or experience_level).strip()
    db_exp = (payload.get("database_experience") or experience_level).strip()

    planner_metadata = (
        f"project_type={project_type}; "
        f"experience_level={experience_level}; "
        f"language_framework={language_framework}; "
        f"time_management_style={time_management_style}; "
        f"memory_style={memory_style}; "
        f"target_deadline={target_deadline or 'none'}"
    )
    stored_notes = f"{notes}\n\nPlanner metadata: {planner_metadata}".strip()

    conn = _connect(db_path)
    try:
        cursor = conn.execute(
            """
            INSERT INTO project_profiles (
                user_id,
                project_name,
                web_experience,
                desktop_experience,
                architecture_experience,
                database_experience,
                target_deadline,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, project_name, web_exp, desktop_exp, architecture_exp, db_exp, target_deadline, stored_notes),
        )
        conn.commit()
        return {
            "id": cursor.lastrowid,
            "project_name": project_name,
            "project_type": project_type,
            "experience_level": experience_level,
            "language_framework": language_framework,
            "time_management_style": time_management_style,
            "memory_style": memory_style,
            "target_deadline": target_deadline,
            "web_experience": web_exp,
            "desktop_experience": desktop_exp,
            "architecture_experience": architecture_exp,
            "database_experience": db_exp,
            "notes": notes,
            "stored_notes": stored_notes,
        }
    finally:
        conn.close()


def _parse_planner_metadata(notes: str) -> dict[str, str]:
    marker = "Planner metadata:"
    if marker not in notes:
        return {}

    metadata_text = notes.split(marker, 1)[1].strip()
    parsed: dict[str, str] = {}
    for chunk in metadata_text.split(";"):
        piece = chunk.strip()
        if "=" not in piece:
            continue
        key, value = piece.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key:
            parsed[key] = value
    return parsed


def get_latest_project_profile(user_id: int, db_path: str) -> dict[str, Any] | None:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT id, project_name, web_experience, desktop_experience, architecture_experience,
                   database_experience, target_deadline, notes
            FROM project_profiles
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return None

    metadata = _parse_planner_metadata(str(row["notes"] or ""))
    return {
        "id": row["id"],
        "project_name": row["project_name"],
        "web_experience": row["web_experience"],
        "desktop_experience": row["desktop_experience"],
        "architecture_experience": row["architecture_experience"],
        "database_experience": row["database_experience"],
        "target_deadline": row["target_deadline"],
        "project_type": metadata.get("project_type", ""),
        "experience_level": metadata.get("experience_level", ""),
        "language_framework": metadata.get("language_framework", ""),
        "time_management_style": metadata.get("time_management_style", ""),
        "memory_style": metadata.get("memory_style", ""),
    }


