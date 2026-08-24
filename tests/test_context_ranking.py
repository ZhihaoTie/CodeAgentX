"""Tests for ranked context selection."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from codeagentx.context_engine import ContextRanker


class TestContextRanker(unittest.TestCase):
    def test_ranks_ast_text_failed_tests_and_recent_patches(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            package = root / "pkg"
            tests = root / "tests"
            package.mkdir()
            tests.mkdir()
            (package / "auth.py").write_text(
                "\n".join([
                    "def login_user(username, password):",
                    "    return username == 'admin'",
                    "",
                    "def logout_user(session):",
                    "    return None",
                    "",
                ]),
                encoding="utf-8",
            )
            (tests / "test_auth.py").write_text(
                "\n".join([
                    "from pkg.auth import login_user",
                    "",
                    "def test_login_failure():",
                    "    assert login_user('admin', 'pw')",
                    "",
                ]),
                encoding="utf-8",
            )
            reflection_report = {
                "signals": [{
                    "category": "test_failure",
                    "message": "pytest reported a failed login test",
                    "evidence": {
                        "failure_names": ["tests/test_auth.py::test_login_failure"],
                    },
                }],
                "retryable": True,
            }

            report = ContextRanker(root).rank(
                goal="fix login failure",
                reflection_report=reflection_report,
                patches=[{"path": "pkg/auth.py"}],
                limit=6,
            )

        paths = [candidate.path for candidate in report.candidates]
        sources = {source for candidate in report.candidates for source in candidate.sources}

        self.assertEqual(report.status, "generated")
        self.assertIn("pkg/auth.py", paths)
        self.assertIn("tests/test_auth.py", paths)
        self.assertIn("ast", sources)
        self.assertIn("text", sources)
        self.assertIn("recent_patch", sources)
        self.assertIn("failed_test", sources)
        self.assertIn("login", report.query_terms)
        self.assertIn("Ranked context:", report.format_block())

    def test_returns_empty_report_when_no_candidates(self):
        with tempfile.TemporaryDirectory() as tempdir:
            Path(tempdir, "app.py").write_text("x = 1\n", encoding="utf-8")

            report = ContextRanker(tempdir).rank(goal="zzznomatch", limit=3)

        self.assertEqual(report.status, "empty")
        self.assertEqual(report.candidates, [])


if __name__ == "__main__":
    unittest.main()
