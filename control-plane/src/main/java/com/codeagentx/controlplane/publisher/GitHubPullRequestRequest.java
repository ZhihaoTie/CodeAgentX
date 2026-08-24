package com.codeagentx.controlplane.publisher;

public class GitHubPullRequestRequest {
    private final String title;
    private final String head;
    private final String base;
    private final String body;

    public GitHubPullRequestRequest(String title, String head, String base, String body) {
        this.title = title;
        this.head = head;
        this.base = base;
        this.body = body;
    }

    public String getTitle() {
        return title;
    }

    public String getHead() {
        return head;
    }

    public String getBase() {
        return base;
    }

    public String getBody() {
        return body;
    }
}
