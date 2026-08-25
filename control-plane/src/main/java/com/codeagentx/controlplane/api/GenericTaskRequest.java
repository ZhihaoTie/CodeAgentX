package com.codeagentx.controlplane.api;

import javax.validation.constraints.NotBlank;

public class GenericTaskRequest {
    @NotBlank
    private String title;

    @NotBlank
    private String body;

    private String idempotencyKey;
    private String externalTaskId;
    private String resultCallbackUrl;
    private String repositoryUrl;
    private String repositoryFullName;
    private String baseBranch;
    private String verificationCommand;

    public String getTitle() { return title; }
    public void setTitle(String title) { this.title = title; }

    public String getBody() { return body; }
    public void setBody(String body) { this.body = body; }

    public String getIdempotencyKey() { return idempotencyKey; }
    public void setIdempotencyKey(String idempotencyKey) { this.idempotencyKey = idempotencyKey; }

    public String getExternalTaskId() { return externalTaskId; }
    public void setExternalTaskId(String externalTaskId) { this.externalTaskId = externalTaskId; }

    public String getResultCallbackUrl() { return resultCallbackUrl; }
    public void setResultCallbackUrl(String resultCallbackUrl) { this.resultCallbackUrl = resultCallbackUrl; }

    public String getRepositoryUrl() { return repositoryUrl; }
    public void setRepositoryUrl(String repositoryUrl) { this.repositoryUrl = repositoryUrl; }

    public String getRepositoryFullName() { return repositoryFullName; }
    public void setRepositoryFullName(String repositoryFullName) { this.repositoryFullName = repositoryFullName; }

    public String getBaseBranch() { return baseBranch; }
    public void setBaseBranch(String baseBranch) { this.baseBranch = baseBranch; }

    public String getVerificationCommand() { return verificationCommand; }
    public void setVerificationCommand(String verificationCommand) { this.verificationCommand = verificationCommand; }
}
