import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.links import extract_links


class ExtractLinksTests(unittest.TestCase):
    def test_extracts_markdown_link_targets_in_order(self):
        markdown = "Read [docs](https://example.com/docs) and [API](/api/reference)."

        self.assertEqual(extract_links(markdown), ["https://example.com/docs", "/api/reference"])

    def test_ignores_plain_urls_without_markdown_syntax(self):
        markdown = "Visit https://example.com or [home](/)."

        self.assertEqual(extract_links(markdown), ["/"])


if __name__ == "__main__":
    unittest.main()
