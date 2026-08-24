"""Tests for structured test result parsing."""

from __future__ import annotations

import unittest

from codeagentx.verification import TestFramework, TestRunStatus, parse_test_output


class TestStructuredTestParser(unittest.TestCase):
    def test_parses_unittest_ok(self):
        output = """
test_demo (tests.TestDemo.test_demo) ... ok

----------------------------------------------------------------------
Ran 3 tests in 0.012s

OK
""".strip()

        result = parse_test_output(stderr=output)

        self.assertEqual(result.framework, TestFramework.UNITTEST)
        self.assertEqual(result.status, TestRunStatus.PASSED)
        self.assertEqual(result.total, 3)
        self.assertEqual(result.passed, 3)
        self.assertEqual(result.failed, 0)
        self.assertEqual(result.duration_seconds, 0.012)

    def test_parses_unittest_failed(self):
        output = """
FAIL: test_math (tests.TestMath.test_math)
Traceback (most recent call last):
  AssertionError: 1 != 2

======================================================================
ERROR: test_io (tests.TestMath.test_io)
Traceback (most recent call last):
  RuntimeError: boom

----------------------------------------------------------------------
Ran 4 tests in 0.100s

FAILED (failures=1, errors=1, skipped=1)
""".strip()

        result = parse_test_output(stderr=output)

        self.assertEqual(result.framework, TestFramework.UNITTEST)
        self.assertEqual(result.status, TestRunStatus.FAILED)
        self.assertEqual(result.total, 4)
        self.assertEqual(result.passed, 1)
        self.assertEqual(result.failed, 1)
        self.assertEqual(result.errors, 1)
        self.assertEqual(result.skipped, 1)
        self.assertEqual(result.failure_names, [
            "test_math (tests.TestMath.test_math)",
            "test_io (tests.TestMath.test_io)",
        ])

    def test_parses_pytest_summary(self):
        output = """
FAILED tests/test_math.py::test_add - AssertionError: 1 != 2
================== 1 failed, 3 passed, 2 skipped in 0.42s ==================
""".strip()

        result = parse_test_output(stdout=output)

        self.assertEqual(result.framework, TestFramework.PYTEST)
        self.assertEqual(result.status, TestRunStatus.FAILED)
        self.assertEqual(result.total, 6)
        self.assertEqual(result.passed, 3)
        self.assertEqual(result.failed, 1)
        self.assertEqual(result.skipped, 2)
        self.assertEqual(result.failure_names, [
            "tests/test_math.py::test_add - AssertionError: 1 != 2",
        ])

    def test_parses_pytest_no_tests(self):
        result = parse_test_output(stdout="no tests ran in 0.03s")

        self.assertEqual(result.framework, TestFramework.PYTEST)
        self.assertEqual(result.status, TestRunStatus.PASSED)
        self.assertEqual(result.total, 0)
        self.assertEqual(result.passed, 0)

    def test_returns_unknown_for_unrecognized_output(self):
        result = parse_test_output(stdout="hello world")

        self.assertEqual(result.framework, TestFramework.UNKNOWN)
        self.assertEqual(result.status, TestRunStatus.UNKNOWN)
        self.assertFalse(result.recognized)


if __name__ == "__main__":
    unittest.main()
