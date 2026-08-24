import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.query import build_query


class BuildQueryTests(unittest.TestCase):
    def test_sorts_keys_for_stable_output(self):
        self.assertEqual(build_query({"b": 2, "a": 1}), "a=1&b=2")

    def test_skips_none_values(self):
        self.assertEqual(build_query({"page": 2, "q": None}), "page=2")

    def test_url_encodes_spaces_and_symbols(self):
        self.assertEqual(build_query({"q": "red shoes", "tag": "a&b"}), "q=red+shoes&tag=a%26b")


if __name__ == "__main__":
    unittest.main()
