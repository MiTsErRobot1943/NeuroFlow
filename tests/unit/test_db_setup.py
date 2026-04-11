"""
Unit tests for db_setup.py authentication helpers.
"""

import os
import tempfile
import unittest
from typing import Any
from typing import cast

from db_setup import create_user, get_user_onboarding, initialize_database, save_user_onboarding, verify_user


class TestDbSetupAuth(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "auth.db")
        initialize_database(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_create_user_success(self):
        created = create_user("valid_user", "StrongPass123!", self.db_path)
        self.assertTrue(created)

        user = verify_user("valid_user", "StrongPass123!", self.db_path)
        self.assertIsNotNone(user)
        onboarding = get_user_onboarding(user["id"], self.db_path)
        self.assertIsNotNone(onboarding)
        self.assertTrue(onboarding["required"])

    def test_create_user_duplicate_username_returns_false(self):
        create_user("duplicate_user", "StrongPass123!", self.db_path)
        created_again = create_user("duplicate_user", "StrongPass123!", self.db_path)
        self.assertFalse(created_again)

    def test_create_user_invalid_username_returns_false(self):
        created = create_user("bad space", "StrongPass123!", self.db_path)
        self.assertFalse(created)

    def test_create_user_short_password_returns_false(self):
        created = create_user("short_pass_user", "short", self.db_path)
        self.assertFalse(created)

    def test_verify_user_success(self):
        create_user("login_user", "StrongPass123!", self.db_path)
        user = verify_user("login_user", "StrongPass123!", self.db_path)
        self.assertIsNotNone(user)
        self.assertEqual(user["username"], "login_user")

    def test_verify_user_wrong_password_returns_none(self):
        create_user("wrong_pass_user", "StrongPass123!", self.db_path)
        user = verify_user("wrong_pass_user", "WrongPass123!", self.db_path)
        self.assertIsNone(user)

    def test_save_user_onboarding_marks_complete_and_persists_answers(self):
        create_user("onboard_user", "StrongPass123!", self.db_path)
        user = verify_user("onboard_user", "StrongPass123!", self.db_path)
        self.assertIsNotNone(user)

        saved = save_user_onboarding(
            user["id"],
            {
                "programming_knowledge": "intermediate",
                "has_project_experience": True,
                "project_examples": "Built a class project",
                "learning_difficulties": ["dyslexia", "adhd"],
            },
            self.db_path,
        )
        self.assertEqual(saved["programming_knowledge"], "intermediate")
        self.assertTrue(saved["has_project_experience"])
        self.assertEqual(saved["learning_difficulties"], ["dyslexia", "adhd"])

        onboarding = get_user_onboarding(user["id"], self.db_path)
        self.assertFalse(onboarding["required"])
        self.assertIsNotNone(onboarding["completed_at"])
        onboarding_data = cast(dict[str, Any], onboarding["data"])
        self.assertEqual(onboarding_data["programming_knowledge"], "intermediate")


if __name__ == "__main__":
    unittest.main()

