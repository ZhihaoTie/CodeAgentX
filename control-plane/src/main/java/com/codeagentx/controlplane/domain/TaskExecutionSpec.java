package com.codeagentx.controlplane.domain;

public class TaskExecutionSpec {
    private final String source;
    private final String title;
    private final String body;
    private final String idempotencyKey;
    private final String repositoryUrl;
    private final String repositoryFullName;
    private final String baseBranch;
    private final String workspaceRoot;
    private final String verificationCommand;

    public TaskExecutionSpec(
        String source,
        String title,
        String body,
        String idempotencyKey,
        String repositoryUrl,
        String repositoryFullName,
        String baseBranch,
        String workspaceRoot,
        String verificationCommand
    ) {
        this.source = source;
        this.title = title;
        this.body = body;
        this.idempotencyKey = idempotencyKey;
        this.repositoryUrl = repositoryUrl;
        this.repositoryFullName = repositoryFullName;
        this.baseBranch = baseBranch;
        this.workspaceRoot = workspaceRoot;
        this.verificationCommand = verificationCommand;
    }

    public String getSource() { return source; }
    public String getTitle() { return title; }
    public String getBody() { return body; }
    public String getIdempotencyKey() { return idempotencyKey; }
    public String getRepositoryUrl() { return repositoryUrl; }
    public String getRepositoryFullName() { return repositoryFullName; }
    public String getBaseBranch() { return baseBranch; }
    public String getWorkspaceRoot() { return workspaceRoot; }
    public String getVerificationCommand() { return verificationCommand; }
}
