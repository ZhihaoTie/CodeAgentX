package com.codeagentx.controlplane.workspace;

public class PatchCommitResult {
    private final String commitSha;
    private final String detail;

    public PatchCommitResult(String commitSha, String detail) {
        this.commitSha = commitSha;
        this.detail = detail;
    }

    public String getCommitSha() {
        return commitSha;
    }

    public String getDetail() {
        return detail;
    }
}
