package com.codeagentx.controlplane.publisher;

public class PublishResult {
    private final String pullRequestUrl;

    public PublishResult(String pullRequestUrl) {
        this.pullRequestUrl = pullRequestUrl;
    }

    public String getPullRequestUrl() {
        return pullRequestUrl;
    }
}
