import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.text_utils import slugify


class SlugifyTests(unittest.TestCase):
    def test_removes_punctuation(self):
        self.assertEqual(slugify("Hello, World!"), "hello-world")

    def test_collapses_whitespace(self):
        self.assertEqual(slugify("  Multiple   spaces  "), "multiple-spaces")

    def test_drops_symbol_runs(self):
        self.assertEqual(slugify("Symbols & Stuff"), "symbols-stuff")


if __name__ == "__main__":
    unittest.main()
