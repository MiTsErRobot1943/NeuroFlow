"""
Unit tests for src/services/task_store.py.

Uses an in-memory SQLite database initialised with the application schema,
so no external services are required.
"""

import os
import sqlite3
import tempfile
import unittest

from db_setup import create_user, initialize_database
from src.services.task_store import (
    add_subtask,
    append_chat_message,
    create_task,
    create_task_list,
    delete_task,
    get_task,
    list_chat_history,
    list_task_lists,
    list_tasks,
    set_subtask_done,
    set_task_done,
)


class TaskStoreTestBase(unittest.TestCase):
    """Base class: creates a fresh database for every test."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test.db")
        initialize_database(self.db_path)
        create_user("testuser", "StrongPass123!", self.db_path)
        # Resolve the actual user ID from the DB
        conn = sqlite3.connect(self.db_path)
        row = conn.execute("SELECT id FROM users WHERE username = 'testuser'").fetchone()
        conn.close()
        self.user_id = row[0]

    def tearDown(self):
        self.temp_dir.cleanup()

    # ── helpers ──────────────────────────────────────────────────────────────
    def _make_list(self, name: str = "Work") -> dict:
        return create_task_list(self.user_id, name, self.db_path)

    def _make_task(self, title: str = "My Task", list_id=None, subtasks=None) -> dict:
        lst = self._make_list()
        return create_task(
            user_id=self.user_id,
            title=title,
            list_id=list_id or lst["id"],
            notes="test notes",
            subtasks=subtasks or [],
            db_path=self.db_path,
        )


class TestTaskLists(TaskStoreTestBase):
    """Tests for task-list CRUD."""

    def test_create_task_list_returns_dict_with_id_and_name(self):
        lst = create_task_list(self.user_id, "Sprint 1", self.db_path)
        self.assertIn("id", lst)
        self.assertEqual(lst["name"], "Sprint 1")

    def test_list_task_lists_includes_general_default(self):
        """list_task_lists always ensures a 'General' list exists."""
        lists = list_task_lists(self.user_id, self.db_path)
        names = [lst["name"] for lst in lists]
        self.assertIn("General", names)

    def test_list_task_lists_returns_custom_lists(self):
        create_task_list(self.user_id, "Backlog", self.db_path)
        names = [lst["name"] for lst in list_task_lists(self.user_id, self.db_path)]
        self.assertIn("Backlog", names)

    def test_create_task_list_idempotent_on_duplicate_name(self):
        """Creating the same list twice should not raise; second call returns same list."""
        lst_a = create_task_list(self.user_id, "Stable", self.db_path)
        lst_b = create_task_list(self.user_id, "Stable", self.db_path)
        self.assertEqual(lst_a["id"], lst_b["id"])

    def test_create_task_list_empty_name_raises(self):
        with self.assertRaises(ValueError):
            create_task_list(self.user_id, "", self.db_path)


class TestCreateTask(TaskStoreTestBase):
    """Tests for create_task and get_task."""

    def test_create_task_returns_dict_with_expected_keys(self):
        task = self._make_task("Deploy service")
        for key in ("id", "title", "notes", "done", "list_id", "list_name", "subtasks", "source"):
            self.assertIn(key, task)

    def test_create_task_stores_title(self):
        task = self._make_task("Write documentation")
        self.assertEqual(task["title"], "Write documentation")

    def test_create_task_not_done_by_default(self):
        task = self._make_task()
        self.assertFalse(task["done"])

    def test_create_task_with_subtasks(self):
        task = self._make_task("Epic", subtasks=["Sub A", "Sub B"])
        self.assertEqual(len(task["subtasks"]), 2)
        titles = [s["title"] for s in task["subtasks"]]
        self.assertIn("Sub A", titles)
        self.assertIn("Sub B", titles)

    def test_create_task_empty_title_raises(self):
        lst = self._make_list()
        with self.assertRaises(ValueError):
            create_task(self.user_id, "", lst["id"], "", [], self.db_path)

    def test_get_task_by_id(self):
        original = self._make_task("Fetch me")
        fetched = get_task(self.user_id, original["id"], self.db_path)
        self.assertEqual(fetched["id"], original["id"])
        self.assertEqual(fetched["title"], "Fetch me")

    def test_list_tasks_returns_created_task(self):
        self._make_task("Listed task")
        tasks = list_tasks(self.user_id, self.db_path)
        titles = [t["title"] for t in tasks]
        self.assertIn("Listed task", titles)


class TestSetTaskDone(TaskStoreTestBase):
    """Tests for set_task_done."""

    def test_mark_task_done(self):
        task = self._make_task()
        updated = set_task_done(self.user_id, task["id"], True, self.db_path)
        self.assertTrue(updated["done"])

    def test_unmark_task_done(self):
        task = self._make_task()
        set_task_done(self.user_id, task["id"], True, self.db_path)
        updated = set_task_done(self.user_id, task["id"], False, self.db_path)
        self.assertFalse(updated["done"])

    def test_set_task_done_nonexistent_task_raises(self):
        with self.assertRaises(ValueError):
            set_task_done(self.user_id, 9999, True, self.db_path)


class TestSubtasks(TaskStoreTestBase):
    """Tests for add_subtask and set_subtask_done."""

    def test_add_subtask_to_task(self):
        task = self._make_task()
        sub = add_subtask(self.user_id, task["id"], "New subtask", self.db_path)
        self.assertEqual(sub["title"], "New subtask")
        self.assertFalse(sub["done"])

    def test_add_subtask_empty_title_raises(self):
        task = self._make_task()
        with self.assertRaises(ValueError):
            add_subtask(self.user_id, task["id"], "  ", self.db_path)

    def test_set_subtask_done(self):
        task = self._make_task("Task", subtasks=["Alpha"])
        subtask_id = task["subtasks"][0]["id"]
        updated_task = set_subtask_done(self.user_id, subtask_id, True, self.db_path)
        subtask = next(s for s in updated_task["subtasks"] if s["id"] == subtask_id)
        self.assertTrue(subtask["done"])

    def test_all_subtasks_done_marks_task_done(self):
        task = self._make_task("Parent", subtasks=["A", "B"])
        for sub in task["subtasks"]:
            result = set_subtask_done(self.user_id, sub["id"], True, self.db_path)
        self.assertTrue(result["done"])


class TestDeleteTask(TaskStoreTestBase):
    """Tests for delete_task."""

    def test_delete_task_removes_from_list(self):
        task = self._make_task("To delete")
        delete_task(self.user_id, task["id"], self.db_path)
        tasks = list_tasks(self.user_id, self.db_path)
        ids = [t["id"] for t in tasks]
        self.assertNotIn(task["id"], ids)

    def test_delete_nonexistent_task_raises(self):
        with self.assertRaises(ValueError):
            delete_task(self.user_id, 9999, self.db_path)


class TestChatHistory(TaskStoreTestBase):
    """Tests for append_chat_message and list_chat_history."""

    def test_append_and_list_messages(self):
        append_chat_message(self.user_id, "user", "Hello bot", self.db_path)
        append_chat_message(self.user_id, "assistant", "Hi there!", self.db_path)
        history = list_chat_history(self.user_id, self.db_path)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["role"], "user")
        self.assertEqual(history[1]["role"], "assistant")

    def test_empty_message_is_ignored(self):
        append_chat_message(self.user_id, "user", "  ", self.db_path)
        history = list_chat_history(self.user_id, self.db_path)
        self.assertEqual(len(history), 0)

    def test_list_chat_history_respects_limit(self):
        for i in range(35):
            append_chat_message(self.user_id, "user", f"Message {i}", self.db_path)
        history = list_chat_history(self.user_id, self.db_path, limit=10)
        self.assertEqual(len(history), 10)

    def test_chat_history_ordered_chronologically(self):
        append_chat_message(self.user_id, "user", "First", self.db_path)
        append_chat_message(self.user_id, "assistant", "Second", self.db_path)
        history = list_chat_history(self.user_id, self.db_path)
        self.assertEqual(history[0]["message"], "First")
        self.assertEqual(history[1]["message"], "Second")


if __name__ == "__main__":
    unittest.main()
