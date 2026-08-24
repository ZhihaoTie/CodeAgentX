package com.codeagentx.controlplane.github;

import java.util.Map;

public class GitHubWorkflowRunWebhook {
    private final boolean supported;
    private final String headBranch;
    private final String status;
    private final String conclusion;
    private final String url;

    private GitHubWorkflowRunWebhook(
        boolean supported,
        String headBranch,
        String status,
        String conclusion,
        String url
    ) {
        this.supported = supported;
        this.headBranch = headBranch;
        this.status = status;
        this.conclusion = conclusion;
        this.url = url;
    }

    public static GitHubWorkflowRunWebhook ignored() {
        return new GitHubWorkflowRunWebhook(false, null, null, null, null);
    }

    public static GitHubWorkflowRunWebhook from(String event, Map<String, Object> payload) {
        if (!"workflow_run".equals(event)) {
            return ignored();
        }
        Object workflowRunObject = payload.get("workflow_run");
        if (!(workflowRunObject instanceof Map)) {
            return ignored();
        }
        @SuppressWarnings("unchecked")
        Map<String, Object> workflowRun = (Map<String, Object>) workflowRunObject;
        String headBranch = stringValue(workflowRun.get("head_branch"));
        if (headBranch == null || headBranch.trim().isEmpty()) {
            return ignored();
        }
        return new GitHubWorkflowRunWebhook(
            true,
            headBranch,
            stringValue(workflowRun.get("status")),
            stringValue(workflowRun.get("conclusion")),
            stringValue(workflowRun.get("html_url"))
        );
    }

    public boolean isSupported() {
        return supported;
    }

    public String getHeadBranch() {
        return headBranch;
    }

    public String getStatus() {
        return status;
    }

    public String getConclusion() {
        return conclusion;
    }

    public String getUrl() {
        return url;
    }

    private static String stringValue(Object value) {
        if (value == null) {
            return null;
        }
        return String.valueOf(value);
    }
}
