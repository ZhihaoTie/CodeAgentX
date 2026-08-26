"""Packaging metadata tests."""

from __future__ import annotations

import tomllib
import unittest
from pathlib import Path


class PackagingMetadataTest(unittest.TestCase):
    def test_console_scripts_are_declared(self) -> None:
        pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
        payload = tomllib.loads(pyproject.read_text(encoding="utf-8"))

        scripts = payload["project"]["scripts"]
        self.assertEqual(scripts["codeagentx"], "codeagentx.cli:main")
        self.assertEqual(scripts["codeagentx-runtime"], "codeagentx.service.__main__:main")
        self.assertEqual(
            payload["project"]["optional-dependencies"]["anthropic"],
            ["anthropic>=0.42.0"],
        )


if __name__ == "__main__":
    unittest.main()
