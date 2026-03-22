"""
Desktop mode startup and backend health smoke tests.

Verifies Flask backend starts correctly in desktop mode and responds to HTTP requests.
"""

import os
import tempfile
import unittest
from urllib.request import urlopen
from urllib.error import URLError

from src.desktop_launcher import start_desktop_backend
from src.desktop_launcher import stop_desktop_backend
from src.desktop_launcher import wait_for_backend


class DesktopStartupSmokeTest(unittest.TestCase):
    """Smoke tests for desktop backend startup and health checks."""

    def setUp(self):
        """Initialize test database and environment."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "desktop_smoke.db")
        os.environ["NEUROFLOW_DB_PATH"] = self.db_path
        os.environ["NEUROFLOW_SECRET_KEY"] = "desktop-test-secret"

    def tearDown(self):
        """Clean up test database and environment."""
        self.temp_dir.cleanup()
        os.environ.pop("NEUROFLOW_DB_PATH", None)
        os.environ.pop("NEUROFLOW_SECRET_KEY", None)

    def test_desktop_backend_serves_login_page(self):
        """Test desktop backend starts and serves login page."""
        backend = start_desktop_backend()
        url = f"http://{backend.host}:{backend.port}/login"

        try:
            wait_for_backend(url)
            try:
                with urlopen(url, timeout=2) as response:
                    self.assertEqual(response.status, 200)
            except URLError as exc:
                self.fail(f"Failed to reach backend: {exc}")
        finally:
            stop_desktop_backend(backend)


if __name__ == "__main__":
    unittest.main()

