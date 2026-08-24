package com.codeagentx.controlplane.workspace;

public class PatchPushResult {
    private final String pushedRef;
    private final String detail;

    public PatchPushResult(String pushedRef, String detail) {
        this.pushedRef = pushedRef;
        this.detail = detail;
    }

    public String getPushedRef() {
        return pushedRef;
    }

    public String getDetail() {
        return detail;
    }
}
