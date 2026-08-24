import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.users import unique_users


class UniqueUsersTests(unittest.TestCase):
    def test_keeps_first_user_for_duplicate_id(self):
        users = [
            {"id": 1, "name": "Ana"},
            {"id": 2, "name": "Bo"},
            {"id": 1, "name": "Anastasia"},
        ]

        self.assertEqual(
            unique_users(users),
            [
                {"id": 1, "name": "Ana"},
                {"id": 2, "name": "Bo"},
            ],
        )

    def test_preserves_input_order(self):
        users = [
            {"id": "b", "name": "Beta"},
            {"id": "a", "name": "Alpha"},
        ]

        self.assertEqual([user["id"] for user in unique_users(users)], ["b", "a"])

    def test_does_not_mutate_input(self):
        users = [{"id": 1, "name": "Ana"}]

        unique_users(users)

        self.assertEqual(users, [{"id": 1, "name": "Ana"}])


if __name__ == "__main__":
    unittest.main()
