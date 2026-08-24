package com.codeagentx.controlplane.domain;

public enum RunStatus {
    CREATED,
    QUEUED,
    RUNNING,
    PATCH_PROPOSED,
    NEEDS_REVIEW,
    CHANGES_REQUESTED,
    REVISING,
    APPROVED,
    PR_CREATING,
    PR_CREATED,
    CI_RUNNING,
    SUCCEEDED,
    FAILED,
    CANCELLED
}
