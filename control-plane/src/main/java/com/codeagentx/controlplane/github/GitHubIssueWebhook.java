package com.codeagentx.controlplane.github;

import java.util.Map;

public class GitHubIssueWebhook {
    private final boolean supported;
    private final String idempotencyKey;
    private final String title;
    private final String body;
    private final String repositoryUrl;
    private final String repositoryFullName;
    private final String baseBranch;

    private GitHubIssueWebhook(
        boolean supported,
        String idempotencyKey,
        String title,
        String body,
        String repositoryUrl,
        String repositoryFullName,
        String baseBranch
    ) {
        this.supported = supported;
        this.idempotencyKey = idempotencyKey;
        this.title = title;
        this.body = body;
        this.repositoryUrl = repositoryUrl;
        this.repositoryFullName = repositoryFullName;
        this.baseBranch = baseBranch;
    }

    public static GitHubIssueWebhook ignored() {
        return new GitHubIssueWebhook(false, null, null, null, null, null, null);
    }

    public static GitHubIssueWebhook from(String event, String deliveryId, Map<String, Object> payload) {
        if (!"issues".equals(event)) {
            return ignored();
        }
        String action = stringValue(payload.get("action"));
        if (!("opened".equals(action) || "reopened".equals(action) || "labeled".equals(action))) {
            return ignored();
        }
        Object issueObject = payload.get("issue");
        if (!(issueObject instanceof Map)) {
            return ignored();
        }
        @SuppressWarnings("unchecked")
        Map<String, Object> issue = (Map<String, Object>) issueObject;

        String title = stringValue(issue.get("title"));
        if (title == null || title.trim().isEmpty()) {
            return ignored();
        }

        StringBuilder body = new StringBuilder();
        body.append(nullToEmpty(stringValue(issue.get("body"))));
        String issueUrl = stringValue(issue.get("html_url"));
        if (issueUrl != null && !issueUrl.trim().isEmpty()) {
            body.append("\n\nGitHub Issue: ").append(issueUrl);
        }
        Map<String, Object> repository = repository(payload);
        String repoName = repository == null ? null : stringValue(repository.get("full_name"));
        if (repoName != null && !repoName.trim().isEmpty()) {
            body.append("\nRepository: ").append(repoName);
        }
        String repositoryUrl = repositoryUrl(repository);
        String baseBranch = repository == null ? null : stringValue(repository.get("default_branch"));

        return new GitHubIssueWebhook(
            true,
            deliveryId == null || deliveryId.trim().isEmpty() ? null : "github:" + deliveryId.trim(),
            title,
            body.toString().trim(),
            repositoryUrl,
            repoName,
            baseBranch
        );
    }

    public boolean isSupported() {
        return supported;
    }

    public String getIdempotencyKey() {
        return idempotencyKey;
    }

    public String getTitle() {
        return title;
    }

    public String getBody() {
        return body;
    }

    public String getRepositoryUrl() {
        return repositoryUrl;
    }

    public String getRepositoryFullName() {
        return repositoryFullName;
    }

    public String getBaseBranch() {
        return baseBranch;
    }

    private static Map<String, Object> repository(Map<String, Object> payload) {
        Object repositoryObject = payload.get("repository");
        if (!(repositoryObject instanceof Map)) {
            return null;
        }
        @SuppressWarnings("unchecked")
        Map<String, Object> repository = (Map<String, Object>) repositoryObject;
        return repository;
    }

    private static String repositoryUrl(Map<String, Object> repository) {
        if (repository == null) {
            return null;
        }
        String cloneUrl = stringValue(repository.get("clone_url"));
        if (cloneUrl != null && !cloneUrl.trim().isEmpty()) {
            return cloneUrl;
        }
        return stringValue(repository.get("html_url"));
    }

    private static String stringValue(Object value) {
        if (value == null) {
            return null;
        }
        return String.valueOf(value);
    }

    private static String nullToEmpty(String value) {
        return value == null ? "" : value;
    }
}
