"""
Integration tests for the NeuroFlow Flask application routes.

Every test starts from a fresh SQLite database and an isolated Flask test
client so that tests are fully independent.  No network services (PostgreSQL,
Ollama) are required: the analytics store and chatbot module both have
documented graceful-fallback paths that are exercised here.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from db_setup import create_user, initialize_database
from src.app_factory import create_app

TEST_USER = "integtester"
TEST_PASS = "StrongPass456!"


class ApiTestBase(unittest.TestCase):
    """Base class: spins up a fresh app + DB for every test method."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "integ.db")
        os.environ["NEUROFLOW_DB_PATH"] = self.db_path
        os.environ["NEUROFLOW_SECRET_KEY"] = "integ-test-secret"

        initialize_database(self.db_path)
        create_user(TEST_USER, TEST_PASS, self.db_path)

        self.app = create_app(mode="dev", init_db=False)
        self.app.testing = True
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()
        os.environ.pop("NEUROFLOW_DB_PATH", None)
        os.environ.pop("NEUROFLOW_SECRET_KEY", None)

    # ── helpers ──────────────────────────────────────────────────────────────

    def _csrf(self) -> str:
        """Obtain a CSRF token from the current session."""
        with self.client.session_transaction() as sess:
            token = sess.get("csrf_token")
        self.assertIsNotNone(token, "CSRF token not found in session")
        return token

    def _login(self) -> None:
        """Perform a full login so subsequent requests are authenticated."""
        self.client.get("/login")
        csrf = self._csrf()
        self.client.post(
            "/login",
            data={"username": TEST_USER, "password": TEST_PASS, "csrf_token": csrf},
            follow_redirects=True,
        )

    def _json_post(self, url: str, payload: dict) -> object:
        csrf = self._csrf()
        return self.client.post(
            url,
            data=json.dumps(payload),
            content_type="application/json",
            headers={"X-CSRF-Token": csrf},
        )


# ── Health endpoint ───────────────────────────────────────────────────────────


class TestHealthEndpoint(ApiTestBase):
    def test_health_returns_ok(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["status"], "ok")


# ── Login / Logout ────────────────────────────────────────────────────────────


class TestAuthRoutes(ApiTestBase):
    def test_get_login_returns_200(self):
        resp = self.client.get("/login")
        self.assertEqual(resp.status_code, 200)

    def test_login_success_redirects_to_dashboard(self):
        self.client.get("/login")
        csrf = self._csrf()
        resp = self.client.post(
            "/login",
            data={"username": TEST_USER, "password": TEST_PASS, "csrf_token": csrf},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)

    def test_login_wrong_password_shows_error(self):
        self.client.get("/login")
        csrf = self._csrf()
        resp = self.client.post(
            "/login",
            data={"username": TEST_USER, "password": "wrongpassword", "csrf_token": csrf},
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Invalid username or password", resp.data)

    def test_login_missing_csrf_rejected(self):
        resp = self.client.post(
            "/login",
            data={"username": TEST_USER, "password": TEST_PASS, "csrf_token": "bad"},
            follow_redirects=True,
        )
        self.assertIn(b"Invalid request token", resp.data)

    def test_logout_clears_session_and_redirects(self):
        self._login()
        csrf = self._csrf()
        resp = self.client.post(
            "/logout",
            data=json.dumps({"csrf_token": csrf}),
            content_type="application/json",
            headers={"X-CSRF-Token": csrf},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertNotIn("user_id", sess)


# ── Dashboard ─────────────────────────────────────────────────────────────────


class TestDashboardRoute(ApiTestBase):
    def test_dashboard_redirects_when_unauthenticated(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 302)

    def test_dashboard_renders_when_authenticated(self):
        self._login()
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)


# ── Bootstrap API ─────────────────────────────────────────────────────────────


class TestBootstrapApi(ApiTestBase):
    def test_bootstrap_requires_auth(self):
        resp = self.client.get("/api/bootstrap")
        self.assertEqual(resp.status_code, 401)

    def test_bootstrap_returns_user_and_lists(self):
        self._login()
        resp = self.client.get("/api/bootstrap")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertIn("lists", body)
        self.assertIn("tasks", body)
        self.assertIn("username", body)
        self.assertIn("csrf_token", body)


# ── Tasks API ─────────────────────────────────────────────────────────────────


class TestTasksApi(ApiTestBase):
    def test_list_tasks_requires_auth(self):
        resp = self.client.get("/api/tasks")
        self.assertEqual(resp.status_code, 401)

    def test_create_task_requires_auth(self):
        resp = self.client.post("/api/tasks", json={"title": "X"})
        self.assertEqual(resp.status_code, 401)

    def test_create_and_list_task(self):
        self._login()
        resp = self._json_post("/api/tasks", {"title": "Integration task", "notes": "some notes"})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["task"]["title"], "Integration task")

        list_resp = self.client.get("/api/tasks")
        self.assertEqual(list_resp.status_code, 200)
        titles = [t["title"] for t in list_resp.get_json()["tasks"]]
        self.assertIn("Integration task", titles)

    def test_create_task_without_title_rejected(self):
        self._login()
        # The route calls create_task which raises ValueError for empty title;
        # Flask propagates this in testing mode.
        with self.assertRaises(ValueError):
            self._json_post("/api/tasks", {"title": ""})

    def test_create_task_without_title_returns_500_non_testing_mode(self):
        """In non-testing mode Flask returns a 500 for unhandled ValueError."""
        self.app.testing = False
        try:
            self._login()
            resp = self._json_post("/api/tasks", {"title": ""})
            self.assertEqual(resp.status_code, 500)
        finally:
            self.app.testing = True

    def test_set_task_done(self):
        self._login()
        create_resp = self._json_post(
            "/api/tasks", {"title": "Completable task", "notes": ""}
        )
        task_id = create_resp.get_json()["task"]["id"]

        done_resp = self._json_post(f"/api/tasks/{task_id}/done", {"done": True})
        self.assertEqual(done_resp.status_code, 200)
        self.assertTrue(done_resp.get_json()["task"]["done"])

    def test_delete_task(self):
        self._login()
        create_resp = self._json_post("/api/tasks", {"title": "Deletable task", "notes": ""})
        task_id = create_resp.get_json()["task"]["id"]

        csrf = self._csrf()
        del_resp = self.client.delete(
            f"/api/tasks/{task_id}",
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(del_resp.status_code, 200)
        self.assertTrue(del_resp.get_json()["ok"])

    def test_add_subtask(self):
        self._login()
        task_resp = self._json_post("/api/tasks", {"title": "Parent task", "notes": ""})
        task_id = task_resp.get_json()["task"]["id"]

        sub_resp = self._json_post(f"/api/tasks/{task_id}/subtasks", {"title": "Child step"})
        self.assertEqual(sub_resp.status_code, 200)
        self.assertEqual(sub_resp.get_json()["subtask"]["title"], "Child step")


# ── Task Lists API ────────────────────────────────────────────────────────────


class TestListsApi(ApiTestBase):
    def test_create_list_requires_auth(self):
        resp = self.client.post("/api/lists", json={"name": "My list"})
        self.assertEqual(resp.status_code, 401)

    def test_create_list_success(self):
        self._login()
        resp = self._json_post("/api/lists", {"name": "Feature Sprint"})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["list"]["name"], "Feature Sprint")

    def test_create_list_empty_name_rejected(self):
        self._login()
        resp = self._json_post("/api/lists", {"name": ""})
        self.assertEqual(resp.status_code, 400)


# ── Chatbot API ───────────────────────────────────────────────────────────────


class TestChatbotApi(ApiTestBase):
    def test_chatbot_requires_auth(self):
        resp = self.client.post("/api/chatbot", json={"message": "hi"})
        self.assertEqual(resp.status_code, 401)

    def test_chatbot_requires_message(self):
        self._login()
        resp = self._json_post("/api/chatbot", {"message": ""})
        self.assertEqual(resp.status_code, 400)

    def test_chatbot_fallback_task_creation(self):
        """'create task: X' should trigger task creation via the fallback path."""
        self._login()
        with patch("src.services.chatbot.ollama", None):
            resp = self._json_post(
                "/api/chatbot", {"message": "create task: Write integration tests"}
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["response"]["action"], "create_task")
        self.assertIsNotNone(body["created_task"])
        self.assertEqual(body["created_task"]["title"], "Write integration tests")

    def test_chatbot_fallback_hint_response(self):
        """An unrecognised message should return action='none' with a hint."""
        self._login()
        with patch("src.services.chatbot.ollama", None):
            resp = self._json_post("/api/chatbot", {"message": "what time is it?"})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["response"]["action"], "none")
        self.assertIsNone(body["created_task"])

    def test_chatbot_persists_messages_in_history(self):
        """Both user and assistant messages should appear in subsequent bootstrap."""
        self._login()
        with patch("src.services.chatbot.ollama", None):
            self._json_post("/api/chatbot", {"message": "create task: Persist me"})

        bootstrap = self.client.get("/api/bootstrap").get_json()
        messages = [m["message"] for m in bootstrap["chat_history"]]
        self.assertIn("create task: Persist me", messages)

    def test_chatbot_with_profile_payload(self):
        """The profile key should be accepted without raising an error."""
        self._login()
        profile = {
            "web_experience": "intermediate",
            "desktop_experience": "beginner",
            "architecture_experience": "advanced",
            "database_experience": "beginner",
        }
        with patch("src.services.chatbot.ollama", None):
            resp = self._json_post(
                "/api/chatbot",
                {"message": "create task: Profile test", "profile": profile},
            )
        self.assertEqual(resp.status_code, 200)


# ── Predefined project templates ──────────────────────────────────────────────


class TestPredefinedProjectApi(ApiTestBase):
    def test_predefined_project_requires_auth(self):
        resp = self.client.post("/api/projects/predefined", json={"template": "web"})
        self.assertEqual(resp.status_code, 401)

    def test_predefined_project_web_template(self):
        self._login()
        resp = self._json_post("/api/projects/predefined", {"template": "web"})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertGreater(len(body["created_tasks"]), 0)

    def test_predefined_project_unknown_template_falls_back_to_web(self):
        """Unknown template names should silently use the web template."""
        self._login()
        resp = self._json_post("/api/projects/predefined", {"template": "unknown_template"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])


# ── Project configure API ─────────────────────────────────────────────────────


class TestConfigureProjectApi(ApiTestBase):
    def test_configure_project_requires_auth(self):
        resp = self.client.post("/api/projects/configure", json={})
        self.assertEqual(resp.status_code, 401)

    def test_configure_project_creates_tasks(self):
        self._login()
        payload = {
            "project_name": "My App",
            "web_experience": "intermediate",
            "desktop_experience": "beginner",
            "architecture_experience": "advanced",
            "database_experience": "intermediate",
            "notes": "Testing configure endpoint",
        }
        resp = self._json_post("/api/projects/configure", payload)
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertGreater(len(body["created_tasks"]), 0)


if __name__ == "__main__":
    unittest.main()
