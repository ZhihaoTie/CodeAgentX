package com.codeagentx.controlplane.workspace;

public class WorkspacePreparationResult {
    private final String workspaceRoot;
    private final String detail;

    public WorkspacePreparationResult(String workspaceRoot, String detail) {
        this.workspaceRoot = workspaceRoot;
        this.detail = detail;
    }

    public String getWorkspaceRoot() {
        return workspaceRoot;
    }

    public String getDetail() {
        return detail;
    }
}
