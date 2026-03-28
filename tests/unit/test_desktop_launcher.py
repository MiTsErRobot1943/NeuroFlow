"""
Unit tests for src/desktop_launcher.py.

Tests port discovery, backend wait-timeout, and backend start/stop lifecycle
without opening a real browser window.
"""

import socket
import tempfile
import os
import threading
import time
import unittest

from src.desktop_launcher import (
    _pick_open_port,
    start_desktop_backend,
    stop_desktop_backend,
    wait_for_backend,
)


class TestPickOpenPort(unittest.TestCase):
    """Unit tests for _pick_open_port."""

    def test_returns_integer(self):
        port = _pick_open_port("127.0.0.1")
        self.assertIsInstance(port, int)

    def test_port_is_in_valid_range(self):
        port = _pick_open_port("127.0.0.1")
        self.assertGreater(port, 0)
        self.assertLessEqual(port, 65535)

    def test_port_is_bindable(self):
        """The returned port should still be bindable immediately after the call."""
        port = _pick_open_port("127.0.0.1")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("127.0.0.1", port))
        finally:
            sock.close()

    def test_successive_calls_may_differ(self):
        """Two successive calls may return distinct ports (no guarantee of uniqueness,
        but both must be valid integers)."""
        port_a = _pick_open_port("127.0.0.1")
        port_b = _pick_open_port("127.0.0.1")
        self.assertIsInstance(port_a, int)
        self.assertIsInstance(port_b, int)


class TestWaitForBackend(unittest.TestCase):
    """Unit tests for wait_for_backend timeout behaviour."""

    def test_raises_timeout_error_when_nothing_listening(self):
        """wait_for_backend should raise TimeoutError if the URL never responds."""
        # Use a port that has nothing listening on it.
        port = _pick_open_port("127.0.0.1")
        url = f"http://127.0.0.1:{port}/health"
        with self.assertRaises(TimeoutError):
            wait_for_backend(url, timeout_seconds=0.3)


class TestDesktopBackendLifecycle(unittest.TestCase):
    """Integration-style unit tests for start/stop desktop backend."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "lifecycle.db")
        os.environ["NEUROFLOW_DB_PATH"] = self.db_path
        os.environ["NEUROFLOW_SECRET_KEY"] = "lifecycle-test"

    def tearDown(self):
        self.temp_dir.cleanup()
        os.environ.pop("NEUROFLOW_DB_PATH", None)
        os.environ.pop("NEUROFLOW_SECRET_KEY", None)

    def test_backend_starts_and_stops_cleanly(self):
        """start_desktop_backend should return a running DesktopBackend; stop should clean up."""
        backend = start_desktop_backend()

        self.assertIsNotNone(backend.server)
        self.assertTrue(backend.thread.is_alive())
        self.assertGreater(backend.port, 0)

        stop_desktop_backend(backend)

        # After shutdown the thread should join within the timeout
        self.assertFalse(backend.thread.is_alive())

    def test_backend_serves_health_endpoint(self):
        """The running backend should respond to GET /health."""
        from urllib.request import urlopen

        backend = start_desktop_backend()
        url = f"http://127.0.0.1:{backend.port}/health"
        try:
            wait_for_backend(url, timeout_seconds=10.0)
            with urlopen(url, timeout=2) as resp:
                self.assertEqual(resp.status, 200)
        finally:
            stop_desktop_backend(backend)


if __name__ == "__main__":
    unittest.main()
