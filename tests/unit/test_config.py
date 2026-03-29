"""
Unit tests for src/config.py.

Covers mode resolution, RuntimeConfig field values, and environment-variable
overrides for load_runtime_config.
"""

import os
import tempfile
import unittest

from src.config import _resolve_mode, load_runtime_config


class TestResolveMode(unittest.TestCase):
    """Unit tests for _resolve_mode."""

    def setUp(self):
        os.environ.pop("NEUROFLOW_MODE", None)

    def tearDown(self):
        os.environ.pop("NEUROFLOW_MODE", None)

    def test_dev_mode_accepted(self):
        self.assertEqual(_resolve_mode("dev"), "dev")

    def test_web_mode_accepted(self):
        self.assertEqual(_resolve_mode("web"), "web")

    def test_desktop_mode_accepted(self):
        self.assertEqual(_resolve_mode("desktop"), "desktop")

    def test_mode_is_case_insensitive(self):
        self.assertEqual(_resolve_mode("DEV"), "dev")
        self.assertEqual(_resolve_mode("WEB"), "web")
        self.assertEqual(_resolve_mode("DESKTOP"), "desktop")

    def test_invalid_mode_defaults_to_dev(self):
        self.assertEqual(_resolve_mode("production"), "dev")

    def test_none_argument_falls_back_to_env_var(self):
        os.environ["NEUROFLOW_MODE"] = "web"
        self.assertEqual(_resolve_mode(None), "web")

    def test_none_argument_with_no_env_defaults_to_dev(self):
        self.assertEqual(_resolve_mode(None), "dev")


class TestLoadRuntimeConfig(unittest.TestCase):
    """Unit tests for load_runtime_config."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        os.environ.pop("NEUROFLOW_MODE", None)
        os.environ.pop("NEUROFLOW_DB_PATH", None)
        os.environ.pop("PORT", None)
        os.environ["NEUROFLOW_SECRET_KEY"] = "test-secret"

    def tearDown(self):
        self.temp_dir.cleanup()
        for key in ("NEUROFLOW_MODE", "NEUROFLOW_DB_PATH", "PORT", "NEUROFLOW_SECRET_KEY"):
            os.environ.pop(key, None)

    def test_dev_mode_debug_is_true(self):
        cfg = load_runtime_config("dev")
        self.assertTrue(cfg.debug)
        self.assertEqual(cfg.mode, "dev")

    def test_web_mode_debug_is_false_and_host_is_public(self):
        cfg = load_runtime_config("web")
        self.assertFalse(cfg.debug)
        self.assertEqual(cfg.host, "0.0.0.0")

    def test_desktop_mode_debug_is_false_and_host_is_local(self):
        cfg = load_runtime_config("desktop")
        self.assertFalse(cfg.debug)
        self.assertEqual(cfg.host, "127.0.0.1")

    def test_dev_mode_host_is_local(self):
        cfg = load_runtime_config("dev")
        self.assertEqual(cfg.host, "127.0.0.1")

    def test_default_port_is_5000(self):
        cfg = load_runtime_config("dev")
        self.assertEqual(cfg.port, 5000)

    def test_port_env_var_overrides_default(self):
        os.environ["PORT"] = "8080"
        cfg = load_runtime_config("dev")
        self.assertEqual(cfg.port, 8080)

    def test_db_path_env_override(self):
        custom_path = os.path.join(self.temp_dir.name, "custom.db")
        os.environ["NEUROFLOW_DB_PATH"] = custom_path
        cfg = load_runtime_config("dev")
        self.assertEqual(str(cfg.db_path), custom_path)

    def test_secret_key_from_env(self):
        os.environ["NEUROFLOW_SECRET_KEY"] = "my-secret"
        cfg = load_runtime_config("dev")
        self.assertEqual(cfg.secret_key, "my-secret")

    def test_secret_key_auto_generated_when_not_set(self):
        os.environ.pop("NEUROFLOW_SECRET_KEY", None)
        cfg = load_runtime_config("dev")
        self.assertIsNotNone(cfg.secret_key)
        self.assertGreater(len(cfg.secret_key), 0)

    def test_runtime_config_is_immutable(self):
        """RuntimeConfig is a frozen dataclass; attribute assignment must fail."""
        cfg = load_runtime_config("dev")
        with self.assertRaises((AttributeError, TypeError)):
            cfg.mode = "web"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
