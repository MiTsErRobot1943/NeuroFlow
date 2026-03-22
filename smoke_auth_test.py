"""
Authentication system smoke tests.

Verifies login flow, SQL injection prevention, and XSS output escaping.
"""

import os
import tempfile
import unittest

from src.app_factory import create_app
from src.services import db_setup

# Test credentials
TEST_USERNAME = "testuser"
TEST_PASSWORD = "StrongPass123!"


class AuthSmokeTest(unittest.TestCase):
    """Smoke tests for authentication and security features."""

    def setUp(self):
        """Initialize test database and Flask app."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_neuroflow.db")
        os.environ["NEUROFLOW_DB_PATH"] = self.db_path
        os.environ["NEUROFLOW_SECRET_KEY"] = "test-secret-key"

        db_setup.initialize_database(self.db_path)
        db_setup.create_user(TEST_USERNAME, TEST_PASSWORD, self.db_path)

        self.app = create_app(mode="dev", init_db=False)
        self.app.testing = True
        self.client = self.app.test_client()

    def tearDown(self):
        """Clean up test database and environment."""
        self.temp_dir.cleanup()
        os.environ.pop("NEUROFLOW_DB_PATH", None)
        os.environ.pop("NEUROFLOW_SECRET_KEY", None)

    def _csrf_from_session(self):
        """Extract CSRF token from session."""
        with self.client.session_transaction() as sess:
            token = sess.get("csrf_token")
        self.assertIsNotNone(token)
        return token

    def test_login_success(self):
        """Test successful login redirects to dashboard."""
        self.client.get("/login")
        csrf = self._csrf_from_session()

        response = self.client.post(
            "/login",
            data={
                "username": TEST_USERNAME,
                "password": TEST_PASSWORD,
                "csrf_token": csrf,
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/", response.headers["Location"])

    def test_sql_injection_attempt_rejected(self):
        """Test SQL injection attempts are rejected."""
        self.client.get("/login")
        csrf = self._csrf_from_session()

        response = self.client.post(
            "/login",
            data={
                "username": "' OR 1=1 --",
                "password": "anything",
                "csrf_token": csrf,
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Invalid username or password.", response.data)

    def test_dashboard_escapes_username_output(self):
        """Test dashboard properly escapes username in output."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["username"] = "<script>alert(1)</script>"
            sess["csrf_token"] = "fixed"

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"&lt;script&gt;alert(1)&lt;/script&gt;", response.data)
        self.assertNotIn(b"<script>alert(1)</script>", response.data)


if __name__ == "__main__":
    unittest.main()

