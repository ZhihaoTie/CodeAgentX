package com.codeagentx.controlplane.workspace;

public class PatchBranchPreparationResult {
    private final String branchName;
    private final String detail;

    public PatchBranchPreparationResult(String branchName, String detail) {
        this.branchName = branchName;
        this.detail = detail;
    }

    public String getBranchName() {
        return branchName;
    }

    public String getDetail() {
        return detail;
    }
}
