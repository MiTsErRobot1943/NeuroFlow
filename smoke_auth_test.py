import importlib
import os
import tempfile
import unittest


class AuthSmokeTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_neuroflow.db")
        os.environ["NEUROFLOW_DB_PATH"] = self.db_path
        os.environ["NEUROFLOW_SECRET_KEY"] = "test-secret-key"

        import db_setup

        importlib.reload(db_setup)
        self.db_setup = db_setup
        self.db_setup.initialize_database()
        self.db_setup.create_user("testuser", "StrongPass123!")

        import app as app_module

        importlib.reload(app_module)
        self.app = app_module.app
        self.app.testing = True
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()
        os.environ.pop("NEUROFLOW_DB_PATH", None)
        os.environ.pop("NEUROFLOW_SECRET_KEY", None)

    def _csrf_from_session(self):
        with self.client.session_transaction() as sess:
            token = sess.get("csrf_token")
        self.assertIsNotNone(token)
        return token

    def test_login_success(self):
        self.client.get("/login")
        csrf = self._csrf_from_session()

        response = self.client.post(
            "/login",
            data={"username": "testuser", "password": "StrongPass123!", "csrf_token": csrf},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/", response.headers["Location"])

    def test_sql_injection_attempt_rejected(self):
        self.client.get("/login")
        csrf = self._csrf_from_session()

        response = self.client.post(
            "/login",
            data={"username": "' OR 1=1 --", "password": "anything", "csrf_token": csrf},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Invalid username or password.", response.data)

    def test_dashboard_escapes_username_output(self):
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

