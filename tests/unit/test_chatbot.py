"""
Unit tests for src/services/chatbot.py.

Covers the fallback response path, JSON coercion, and generate_response
behaviour when the optional Ollama dependency is absent.
"""

import unittest
from unittest.mock import patch

from src.services.chatbot import _coerce_response, _fallback_response, generate_response


class TestFallbackResponse(unittest.TestCase):
    """Unit tests for _fallback_response."""

    def test_creates_task_on_exact_pattern(self):
        """'create task: X' should produce a create_task action."""
        result = _fallback_response("create task: Build API auth layer", [])
        self.assertEqual(result["action"], "create_task")
        self.assertIn("Build API auth layer", result["message"])
        self.assertEqual(result["task"]["title"], "Build API auth layer")

    def test_creates_task_with_add_prefix(self):
        """'add task: X' should also trigger task creation."""
        result = _fallback_response("add task: Write unit tests", [])
        self.assertEqual(result["action"], "create_task")
        self.assertEqual(result["task"]["title"], "Write unit tests")

    def test_creates_task_with_dash_separator(self):
        """'create task - X' (dash separator) should trigger task creation."""
        result = _fallback_response("create task - Fix login bug", [])
        self.assertEqual(result["action"], "create_task")
        self.assertEqual(result["task"]["title"], "Fix login bug")

    def test_title_truncated_at_160_chars(self):
        """Task title should be truncated to 160 characters."""
        long_title = "A" * 200
        result = _fallback_response(f"create task: {long_title}", [])
        self.assertEqual(result["action"], "create_task")
        self.assertLessEqual(len(result["task"]["title"]), 160)

    def test_no_match_returns_hint_with_no_tasks(self):
        """An unrecognised message should return action='none' with a usage hint."""
        result = _fallback_response("hello there", [])
        self.assertEqual(result["action"], "none")
        self.assertIn("create task", result["message"].lower())
        self.assertIn("none yet", result["message"])

    def test_no_match_includes_recent_task_titles(self):
        """The hint message should include up to three recent task titles."""
        tasks = [
            {"title": "Task One"},
            {"title": "Task Two"},
            {"title": "Task Three"},
            {"title": "Task Four"},
        ]
        result = _fallback_response("show tasks", tasks)
        self.assertEqual(result["action"], "none")
        self.assertIn("Task One", result["message"])
        self.assertIn("Task Two", result["message"])
        self.assertIn("Task Three", result["message"])
        self.assertNotIn("Task Four", result["message"])

    def test_task_has_required_fields(self):
        """Created task object must include title, notes, subtasks, and list_name."""
        result = _fallback_response("create task: Deploy service", [])
        task = result["task"]
        self.assertIn("title", task)
        self.assertIn("notes", task)
        self.assertIn("subtasks", task)
        self.assertIn("list_name", task)
        self.assertIsInstance(task["subtasks"], list)

    def test_build_request_creates_task_with_subtasks(self):
        """Build-style asks should create a task and include generated subtasks."""
        result = _fallback_response("how to build a flask web app", [])
        self.assertEqual(result["action"], "create_task")
        self.assertTrue(result["task"]["title"].lower().startswith("build "))
        self.assertGreaterEqual(len(result["task"]["subtasks"]), 4)

    def test_set_tasks_for_making_phrase_creates_subtasks(self):
        """Quoted phrasing should map to create_task and produce a practical task breakdown."""
        message = "set tasks for making flappy bird python flask browser game"
        result = _fallback_response(message, [])
        self.assertEqual(result["action"], "create_task")
        self.assertIn("flappy bird", result["task"]["title"].lower())
        self.assertGreaterEqual(len(result["task"]["subtasks"]), 4)

    def test_help_me_make_web_app_creates_step_plan(self):
        """Very brief build prompts should still trigger practical task generation."""
        result = _fallback_response("Help me make a web app", [])
        self.assertEqual(result["action"], "create_task")
        self.assertTrue(result["task"]["title"].lower().startswith("build "))
        self.assertGreaterEqual(len(result["task"]["subtasks"]), 4)

    def test_help_me_learn_javascript_creates_learning_plan_and_session_hint(self):
        """Learning asks should create learning-plan tasks and request a new chat session."""
        result = _fallback_response("Help me learn JavaScript", [])
        self.assertEqual(result["action"], "create_task")
        self.assertTrue(result["task"]["title"].lower().startswith("learn javascript"))
        self.assertGreaterEqual(len(result["task"]["subtasks"]), 4)
        self.assertTrue(result.get("start_new_session"))

    def test_feedback_context_is_reflected_in_hint_message(self):
        feedback_context = {
            "chatbot": {"top_intents": ["learning", "task_planning"]},
            "tasks": {"median_completion_minutes": 35.0},
        }
        result = _fallback_response("hello there", [], feedback_context=feedback_context)
        self.assertIn("learning", result["message"].lower())
        self.assertIn("35.0", result["message"])


class TestCoerceResponse(unittest.TestCase):
    """Unit tests for _coerce_response."""

    def _fallback(self):
        return {"message": "fallback", "action": "none"}

    def test_valid_json_with_message_key_returned(self):
        """Valid JSON containing a 'message' key should be returned as-is."""
        raw = '{"message": "Hello", "action": "none"}'
        result = _coerce_response(raw, self._fallback())
        self.assertEqual(result["message"], "Hello")
        self.assertEqual(result["action"], "none")

    def test_valid_json_without_message_key_returns_fallback(self):
        """Valid JSON missing the 'message' key should return the fallback."""
        raw = '{"action": "none"}'
        result = _coerce_response(raw, self._fallback())
        self.assertEqual(result, self._fallback())

    def test_invalid_json_returns_fallback(self):
        """Invalid JSON should return the fallback dict."""
        result = _coerce_response("not json at all", self._fallback())
        self.assertEqual(result, self._fallback())

    def test_empty_string_returns_fallback(self):
        """An empty string should return the fallback dict."""
        result = _coerce_response("", self._fallback())
        self.assertEqual(result, self._fallback())

    def test_json_array_returns_fallback(self):
        """A JSON array (not a dict) should return the fallback dict."""
        result = _coerce_response('[{"message": "hi"}]', self._fallback())
        self.assertEqual(result, self._fallback())


class TestGenerateResponse(unittest.TestCase):
    """Unit tests for generate_response (Ollama-absent paths)."""

    def test_returns_fallback_when_ollama_absent(self):
        """When ollama module is unavailable, generate_response uses fallback."""
        with patch("src.services.chatbot.ollama", None):
            result = generate_response("create task: Write tests", [])
        self.assertEqual(result["action"], "create_task")
        self.assertEqual(result["task"]["title"], "Write tests")

    def test_no_match_returns_hint_when_ollama_absent(self):
        """Unrecognised message without Ollama returns the hint response."""
        with patch("src.services.chatbot.ollama", None):
            result = generate_response("what is the weather?", [])
        self.assertEqual(result["action"], "none")

    def test_profile_arg_accepted_without_error(self):
        """generate_response should accept a profile dict without raising."""
        profile = {
            "web_experience": "intermediate",
            "desktop_experience": "beginner",
            "architecture_experience": "advanced",
            "database_experience": "intermediate",
        }
        with patch("src.services.chatbot.ollama", None):
            result = generate_response("create task: Deploy app", [], profile=profile)
        self.assertEqual(result["action"], "create_task")

    def test_feedback_context_arg_accepted_without_error(self):
        feedback = {
            "chatbot": {"top_intents": ["learning"]},
            "tasks": {"median_completion_minutes": 18.0},
        }
        with patch("src.services.chatbot.ollama", None):
            result = generate_response("what is the weather?", [], feedback_context=feedback)
        self.assertEqual(result["action"], "none")


if __name__ == "__main__":
    unittest.main()
