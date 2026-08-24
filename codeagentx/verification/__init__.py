"""Outcome verification primitives."""

from .constraints import TaskConstraintEvaluation, TaskConstraintSpec, TaskConstraintVerifier
from .outcome import (
    OutcomeVerifier,
    VerificationCheck,
    VerificationReport,
    VerificationStatus,
)
from .test_parser import (
    StructuredTestResult,
    TestFramework,
    TestRunStatus,
    parse_test_output,
)

__all__ = [
    "OutcomeVerifier",
    "StructuredTestResult",
    "TaskConstraintEvaluation",
    "TaskConstraintSpec",
    "TaskConstraintVerifier",
    "TestFramework",
    "TestRunStatus",
    "VerificationCheck",
    "VerificationReport",
    "VerificationStatus",
    "parse_test_output",
]
