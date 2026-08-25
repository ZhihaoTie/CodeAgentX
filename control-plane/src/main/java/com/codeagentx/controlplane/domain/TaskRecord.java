package com.codeagentx.controlplane.domain;

import java.time.Instant;
import java.util.UUID;

import javax.persistence.Column;
import javax.persistence.Entity;
import javax.persistence.Id;
import javax.persistence.Lob;
import javax.persistence.Table;
import javax.persistence.UniqueConstraint;

@Entity
@Table(
    name = "tasks",
    uniqueConstraints = {
        @UniqueConstraint(name = "uk_tasks_idempotency_key", columnNames = {"idempotency_key"})
    }
)
public class TaskRecord {
    @Id
    @Column(length = 64)
    private String taskId;

    @Column(nullable = false, length = 64)
    private String source;

    @Column(nullable = false)
    private String title;

    @Lob
    @Column(nullable = false)
    private String body;

    @Column(name = "idempotency_key", length = 128)
    private String idempotencyKey;

    @Column(name = "repository_url", length = 512)
    private String repositoryUrl;

    @Column(name = "repository_full_name", length = 256)
    private String repositoryFullName;

    @Column(name = "base_branch", length = 128)
    private String baseBranch;

    @Column(name = "workspace_root", length = 512)
    private String workspaceRoot;

    @Column(name = "verification_command", length = 512)
    private String verificationCommand;

    @Column(name = "external_task_id", length = 256)
    private String externalTaskId;

    @Column(name = "result_callback_url", length = 1024)
    private String resultCallbackUrl;

    @Column(nullable = false)
    private Instant createdAt;

    protected TaskRecord() {
    }

    public TaskRecord(String source, String title, String body) {
        this(source, title, body, null);
    }

    public TaskRecord(String source, String title, String body, String idempotencyKey) {
        this(source, title, body, idempotencyKey, null, null, null, null, null);
    }

    public TaskRecord(
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
        this(source, title, body, idempotencyKey, repositoryUrl, repositoryFullName, baseBranch, workspaceRoot, verificationCommand, null, null);
    }

    public TaskRecord(
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
        this.taskId = UUID.randomUUID().toString();
        this.source = blankToDefault(source, "rest");
        this.title = title;
        this.body = body;
        this.idempotencyKey = normalizeIdempotencyKey(idempotencyKey);
        this.repositoryUrl = blankToNull(repositoryUrl);
        this.repositoryFullName = blankToNull(repositoryFullName);
        this.baseBranch = blankToNull(baseBranch);
        this.workspaceRoot = blankToNull(workspaceRoot);
        this.verificationCommand = blankToNull(verificationCommand);
        this.externalTaskId = blankToNull(externalTaskId);
        this.resultCallbackUrl = blankToNull(resultCallbackUrl);
        this.createdAt = Instant.now();
    }

    public String getTaskId() { return taskId; }
    public String getSource() { return source; }
    public String getTitle() { return title; }
    public String getBody() { return body; }
    public Instant getCreatedAt() { return createdAt; }
    public String getIdempotencyKey() { return idempotencyKey; }
    public String getRepositoryUrl() { return repositoryUrl; }
    public String getRepositoryFullName() { return repositoryFullName; }
    public String getBaseBranch() { return baseBranch; }
    public String getWorkspaceRoot() { return workspaceRoot; }
    public String getVerificationCommand() { return verificationCommand; }
    public String getExternalTaskId() { return externalTaskId; }
    public String getResultCallbackUrl() { return resultCallbackUrl; }

    private String normalizeIdempotencyKey(String idempotencyKey) {
        if (idempotencyKey == null) {
            return null;
        }
        String trimmed = idempotencyKey.trim();
        if (trimmed.isEmpty()) {
            return null;
        }
        return trimmed;
    }

    private String blankToDefault(String value, String defaultValue) {
        String normalized = blankToNull(value);
        return normalized == null ? defaultValue : normalized;
    }

    private String blankToNull(String value) {
        if (value == null) {
            return null;
        }
        String trimmed = value.trim();
        return trimmed.isEmpty() ? null : trimmed;
    }
}
