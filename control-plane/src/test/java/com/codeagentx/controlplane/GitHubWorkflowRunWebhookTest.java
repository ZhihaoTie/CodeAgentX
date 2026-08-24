package com.codeagentx.controlplane;

import com.codeagentx.controlplane.github.GitHubWorkflowRunWebhook;
import org.junit.jupiter.api.Test;

import java.util.HashMap;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class GitHubWorkflowRunWebhookTest {
    @Test
    void parsesWorkflowRunWebhook() {
        Map<String, Object> payload = new HashMap<String, Object>();
        Map<String, Object> workflowRun = new HashMap<String, Object>();
        workflowRun.put("head_branch", "codeagentx/run-123");
        workflowRun.put("status", "completed");
        workflowRun.put("conclusion", "success");
        workflowRun.put("html_url", "https://github.com/acme/repo/actions/runs/1");
        payload.put("workflow_run", workflowRun);

        GitHubWorkflowRunWebhook webhook = GitHubWorkflowRunWebhook.from("workflow_run", payload);

        assertThat(webhook.isSupported()).isTrue();
        assertThat(webhook.getHeadBranch()).isEqualTo("codeagentx/run-123");
        assertThat(webhook.getStatus()).isEqualTo("completed");
        assertThat(webhook.getConclusion()).isEqualTo("success");
        assertThat(webhook.getUrl()).contains("actions/runs/1");
    }

    @Test
    void ignoresUnsupportedWebhook() {
        GitHubWorkflowRunWebhook webhook = GitHubWorkflowRunWebhook.from(
            "issues",
            new HashMap<String, Object>()
        );

        assertThat(webhook.isSupported()).isFalse();
    }
}
