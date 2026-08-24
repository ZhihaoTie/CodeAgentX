package com.codeagentx.controlplane;

import com.codeagentx.controlplane.github.GitHubIssueWebhook;
import org.junit.jupiter.api.Test;

import java.util.HashMap;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class GitHubIssueWebhookTest {
    @Test
    void parsesSupportedIssueWebhook() {
        Map<String, Object> payload = new HashMap<String, Object>();
        payload.put("action", "opened");
        Map<String, Object> issue = new HashMap<String, Object>();
        issue.put("title", "Fix flaky parser");
        issue.put("body", "Parser fails on empty input.");
        issue.put("html_url", "https://github.com/acme/repo/issues/7");
        payload.put("issue", issue);
        Map<String, Object> repository = new HashMap<String, Object>();
        repository.put("full_name", "acme/repo");
        repository.put("clone_url", "https://github.com/acme/repo.git");
        repository.put("default_branch", "main");
        payload.put("repository", repository);

        GitHubIssueWebhook webhook = GitHubIssueWebhook.from("issues", "delivery-7", payload);

        assertThat(webhook.isSupported()).isTrue();
        assertThat(webhook.getIdempotencyKey()).isEqualTo("github:delivery-7");
        assertThat(webhook.getTitle()).isEqualTo("Fix flaky parser");
        assertThat(webhook.getBody()).contains("Parser fails on empty input.");
        assertThat(webhook.getBody()).contains("https://github.com/acme/repo/issues/7");
        assertThat(webhook.getBody()).contains("acme/repo");
        assertThat(webhook.getRepositoryUrl()).isEqualTo("https://github.com/acme/repo.git");
        assertThat(webhook.getRepositoryFullName()).isEqualTo("acme/repo");
        assertThat(webhook.getBaseBranch()).isEqualTo("main");
    }

    @Test
    void ignoresUnsupportedWebhook() {
        GitHubIssueWebhook webhook = GitHubIssueWebhook.from(
            "pull_request",
            "delivery-8",
            new HashMap<String, Object>()
        );

        assertThat(webhook.isSupported()).isFalse();
    }
}
