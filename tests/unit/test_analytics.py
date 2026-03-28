"""
Unit tests for src/services/analytics_store.py.

Focuses on the graceful-fallback behaviour when no database URL is provided
or when the optional psycopg2 driver is absent.  Live PostgreSQL connectivity
is not required.
"""

import unittest
from unittest.mock import MagicMock, patch

from src.services.analytics_store import initialize_analytics_database, track_event


class TestInitializeAnalyticsDatabase(unittest.TestCase):
    """Unit tests for initialize_analytics_database."""

    def test_returns_false_when_url_is_none(self):
        self.assertFalse(initialize_analytics_database(None))

    def test_returns_false_when_url_is_empty_string(self):
        self.assertFalse(initialize_analytics_database(""))

    def test_returns_false_when_psycopg2_unavailable(self):
        with patch("src.services.analytics_store.psycopg2", None):
            self.assertFalse(initialize_analytics_database("postgresql://localhost/test"))

    def test_returns_true_on_successful_connection(self):
        """Simulate a successful psycopg2 connect/cursor cycle."""
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        mock_psycopg2 = MagicMock()
        mock_psycopg2.connect.return_value = mock_conn

        with patch("src.services.analytics_store.psycopg2", mock_psycopg2):
            result = initialize_analytics_database("postgresql://localhost/test")

        self.assertTrue(result)
        mock_psycopg2.connect.assert_called_once_with("postgresql://localhost/test")

    def test_returns_false_on_connection_error(self):
        """A connection error should be caught and return False."""
        mock_psycopg2 = MagicMock()
        mock_psycopg2.connect.side_effect = Exception("connection refused")

        with patch("src.services.analytics_store.psycopg2", mock_psycopg2):
            result = initialize_analytics_database("postgresql://localhost/test")

        self.assertFalse(result)


class TestTrackEvent(unittest.TestCase):
    """Unit tests for track_event."""

    def test_no_op_when_url_is_none(self):
        """track_event must silently do nothing when no URL is given."""
        mock_psycopg2 = MagicMock()
        with patch("src.services.analytics_store.psycopg2", mock_psycopg2):
            track_event(None, "login_success", "alice", {})
        mock_psycopg2.connect.assert_not_called()

    def test_no_op_when_url_is_empty_string(self):
        mock_psycopg2 = MagicMock()
        with patch("src.services.analytics_store.psycopg2", mock_psycopg2):
            track_event("", "login_success", "alice", {})
        mock_psycopg2.connect.assert_not_called()

    def test_no_op_when_psycopg2_unavailable(self):
        with patch("src.services.analytics_store.psycopg2", None):
            # Should not raise
            track_event("postgresql://localhost/test", "event", "user", {})

    def test_inserts_event_row_when_connected(self):
        """track_event should execute an INSERT when a working driver is present."""
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        mock_psycopg2 = MagicMock()
        mock_psycopg2.connect.return_value = mock_conn

        with patch("src.services.analytics_store.psycopg2", mock_psycopg2):
            track_event("postgresql://localhost/test", "task_created", "bob", {"task_id": 1})

        mock_psycopg2.connect.assert_called_once()
        mock_cursor.execute.assert_called_once()

    def test_payload_defaults_to_empty_dict_when_none(self):
        """A None payload should be serialised as an empty JSON object."""
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        mock_psycopg2 = MagicMock()
        mock_psycopg2.connect.return_value = mock_conn

        with patch("src.services.analytics_store.psycopg2", mock_psycopg2):
            track_event("postgresql://localhost/test", "logout", "carol", None)

        args = mock_cursor.execute.call_args[0]
        # Third parameter should be serialised as '{}'
        self.assertIn("{}", args[1][2])


if __name__ == "__main__":
    unittest.main()
