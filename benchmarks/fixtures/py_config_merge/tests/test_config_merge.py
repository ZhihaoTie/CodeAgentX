import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config_merge import merge_config


class MergeConfigTests(unittest.TestCase):
    def test_does_not_mutate_defaults(self):
        defaults = {"timeout": 30, "retries": 2}

        merged = merge_config(defaults, {"timeout": 10})

        self.assertEqual(merged, {"timeout": 10, "retries": 2})
        self.assertEqual(defaults, {"timeout": 30, "retries": 2})

    def test_deep_merges_nested_dicts(self):
        defaults = {
            "timeout": 30,
            "headers": {
                "accept": "application/json",
            },
        }

        merged = merge_config(
            defaults,
            {
                "headers": {
                    "authorization": "Bearer token",
                },
            },
        )

        self.assertEqual(
            merged,
            {
                "timeout": 30,
                "headers": {
                    "accept": "application/json",
                    "authorization": "Bearer token",
                },
            },
        )
        self.assertEqual(defaults["headers"], {"accept": "application/json"})


if __name__ == "__main__":
    unittest.main()
