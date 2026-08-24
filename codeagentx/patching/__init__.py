"""Patch transaction support."""

from .policy import PatchPolicy, PatchPolicyReport, PatchPolicySeverity, PatchPolicyStatus
from .policy import PatchPolicyViolation
from .rollback import PatchRollbackReport, rollback_applied_patches
from .transaction import (
    PatchApplyError,
    PatchApplyResult,
    PatchOperation,
    PatchRollbackResult,
    PatchTransaction,
)

__all__ = [
    "PatchApplyError",
    "PatchApplyResult",
    "PatchOperation",
    "PatchPolicy",
    "PatchPolicyReport",
    "PatchPolicySeverity",
    "PatchPolicyStatus",
    "PatchPolicyViolation",
    "PatchRollbackReport",
    "PatchRollbackResult",
    "PatchTransaction",
    "rollback_applied_patches",
]
