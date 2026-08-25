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
    private final String externalTaskId;
    private final String resultCallbackUrl;
    private final String provider;
    private final String model;
    private final Integer maxTurns;
    private final Double maxRunSeconds;
    private final String permissionMode;

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
        this(source, title, body, idempotencyKey, repositoryUrl, repositoryFullName, baseBranch, workspaceRoot, verificationCommand, null, null, null, null, null, null, null);
    }

    public TaskExecutionSpec(
        String source,
        String title,
        String body,
        String idempotencyKey,
        String repositoryUrl,
        String repositoryFullName,
        String baseBranch,
        String workspaceRoot,
        String verificationCommand,
        String externalTaskId,
        String resultCallbackUrl
    ) {
        this(source, title, body, idempotencyKey, repositoryUrl, repositoryFullName, baseBranch, workspaceRoot, verificationCommand, externalTaskId, resultCallbackUrl, null, null, null, null, null);
    }

    public TaskExecutionSpec(
        String source,
        String title,
        String body,
        String idempotencyKey,
        String repositoryUrl,
        String repositoryFullName,
        String baseBranch,
        String workspaceRoot,
        String verificationCommand,
        String externalTaskId,
        String resultCallbackUrl,
        String provider,
        String model,
        Integer maxTurns,
        Double maxRunSeconds,
        String permissionMode
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
        this.externalTaskId = externalTaskId;
        this.resultCallbackUrl = resultCallbackUrl;
        this.provider = provider;
        this.model = model;
        this.maxTurns = maxTurns;
        this.maxRunSeconds = maxRunSeconds;
        this.permissionMode = permissionMode;
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
    public String getExternalTaskId() { return externalTaskId; }
    public String getResultCallbackUrl() { return resultCallbackUrl; }
    public String getProvider() { return provider; }
    public String getModel() { return model; }
    public Integer getMaxTurns() { return maxTurns; }
    public Double getMaxRunSeconds() { return maxRunSeconds; }
    public String getPermissionMode() { return permissionMode; }
}
