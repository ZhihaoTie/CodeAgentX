package com.codeagentx.controlplane.domain;

import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import javax.persistence.CascadeType;
import javax.persistence.Column;
import javax.persistence.Embedded;
import javax.persistence.Entity;
import javax.persistence.EnumType;
import javax.persistence.Enumerated;
import javax.persistence.FetchType;
import javax.persistence.Id;
import javax.persistence.JoinColumn;
import javax.persistence.Lob;
import javax.persistence.OneToMany;
import javax.persistence.OrderBy;
import javax.persistence.Table;
import org.hibernate.annotations.Fetch;
import org.hibernate.annotations.FetchMode;

@Entity
@Table(name = "runs")
public class RunRecord {
    @Id
    @Column(name = "run_id", length = 64)
    private String runId;

    @Column(nullable = false, length = 64)
    private String taskId;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 32)
    private RunStatus status;

    @Column(length = 64)
    private String runtimeRunId;

    @Column(name = "execution_workspace_root", length = 512)
    private String executionWorkspaceRoot;

    @Column(name = "patch_branch", length = 256)
    private String patchBranch;

    @Column(name = "patch_commit_sha", length = 64)
    private String patchCommitSha;

    @Column(name = "patch_pushed_ref", length = 256)
    private String patchPushedRef;

    @Lob
    private String finalText;

    @Lob
    private String failureReason;

    @Column(length = 512)
    private String pullRequestUrl;

    @Embedded
    private PatchArtifact patchArtifact;

    @Column(nullable = false)
    private Instant createdAt;

    @Column(nullable = false)
    private Instant updatedAt;

    @OneToMany(cascade = CascadeType.ALL, fetch = FetchType.EAGER, orphanRemoval = true)
    @JoinColumn(name = "run_id", referencedColumnName = "run_id", insertable = false, updatable = false)
    @OrderBy("createdAt ASC")
    @Fetch(FetchMode.SUBSELECT)
    private List<ReviewRecord> reviews;

    @OneToMany(cascade = CascadeType.ALL, fetch = FetchType.EAGER, orphanRemoval = true)
    @JoinColumn(name = "run_id", referencedColumnName = "run_id", insertable = false, updatable = false)
    @OrderBy("createdAt ASC")
    @Fetch(FetchMode.SUBSELECT)
    private List<RunEventRecord> events;

    protected RunRecord() {
    }

    public RunRecord(String taskId) {
        this.runId = UUID.randomUUID().toString();
        this.taskId = taskId;
        this.status = RunStatus.CREATED;
        this.createdAt = Instant.now();
        this.updatedAt = this.createdAt;
        this.reviews = new ArrayList<ReviewRecord>();
        this.events = new ArrayList<RunEventRecord>();
        addEvent("RUN_CREATED", Collections.<String, Object>emptyMap());
    }

    public String getRunId() {
        return runId;
    }

    public String getTaskId() {
        return taskId;
    }

    public RunStatus getStatus() {
        return status;
    }

    public void setStatus(RunStatus status) {
        RunStatus previous = this.status;
        if (previous == status) {
            return;
        }
        this.status = status;
        touch();
        Map<String, Object> payload = new LinkedHashMap<String, Object>();
        payload.put("from", previous.name());
        payload.put("to", status.name());
        addEvent("STATUS_CHANGED", payload);
    }

    public String getRuntimeRunId() {
        return runtimeRunId;
    }

    public void setRuntimeRunId(String runtimeRunId) {
        this.runtimeRunId = runtimeRunId;
        touch();
        Map<String, Object> payload = new LinkedHashMap<String, Object>();
        payload.put("runtimeRunId", runtimeRunId);
        addEvent("RUNTIME_RUN_LINKED", payload);
    }

    public String getExecutionWorkspaceRoot() {
        return executionWorkspaceRoot;
    }

    public void setExecutionWorkspaceRoot(String executionWorkspaceRoot) {
        this.executionWorkspaceRoot = executionWorkspaceRoot;
        touch();
        Map<String, Object> payload = new LinkedHashMap<String, Object>();
        payload.put("workspaceRoot", executionWorkspaceRoot);
        addEvent("WORKSPACE_PREPARED", payload);
    }

    public String getPatchBranch() {
        return patchBranch;
    }

    public void setPatchBranch(String patchBranch) {
        this.patchBranch = patchBranch;
        touch();
        Map<String, Object> payload = new LinkedHashMap<String, Object>();
        payload.put("patchBranch", patchBranch);
        addEvent("PATCH_BRANCH_PREPARED", payload);
    }

    public String getPatchCommitSha() {
        return patchCommitSha;
    }

    public void setPatchCommitSha(String patchCommitSha) {
        this.patchCommitSha = patchCommitSha;
        touch();
        Map<String, Object> payload = new LinkedHashMap<String, Object>();
        payload.put("patchCommitSha", patchCommitSha);
        addEvent("PATCH_COMMITTED", payload);
    }

    public String getPatchPushedRef() {
        return patchPushedRef;
    }

    public void setPatchPushedRef(String patchPushedRef) {
        this.patchPushedRef = patchPushedRef;
        touch();
        Map<String, Object> payload = new LinkedHashMap<String, Object>();
        payload.put("patchPushedRef", patchPushedRef);
        addEvent("PATCH_PUSHED", payload);
    }

    public String getFinalText() {
        return finalText;
    }

    public void setFinalText(String finalText) {
        this.finalText = finalText;
        touch();
    }

    public String getFailureReason() {
        return failureReason;
    }

    public void setFailureReason(String failureReason) {
        this.failureReason = failureReason;
        touch();
    }

    public boolean isTimedOut(Instant now, java.time.Duration timeout) {
        if (status != RunStatus.RUNNING && status != RunStatus.REVISING) {
            return false;
        }
        return updatedAt.plus(timeout).isBefore(now) || updatedAt.plus(timeout).equals(now);
    }

    public String getPullRequestUrl() {
        return pullRequestUrl;
    }

    public void setPullRequestUrl(String pullRequestUrl) {
        this.pullRequestUrl = pullRequestUrl;
        touch();
        Map<String, Object> payload = new LinkedHashMap<String, Object>();
        payload.put("pullRequestUrl", pullRequestUrl);
        addEvent("PR_CREATED", payload);
    }

    public PatchArtifact getPatchArtifact() {
        return patchArtifact;
    }

    public void setPatchArtifact(PatchArtifact patchArtifact) {
        this.patchArtifact = patchArtifact;
        touch();
        Map<String, Object> payload = new LinkedHashMap<String, Object>();
        payload.put("hasDiff", patchArtifact != null && patchArtifact.getDiffText() != null);
        payload.put("hasTestReport", patchArtifact != null && patchArtifact.getTestReport() != null);
        payload.put("trajectoryReportPath", patchArtifact == null ? null : patchArtifact.getTrajectoryReportPath());
        addEvent("PATCH_ARTIFACT_RECORDED", payload);
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }

    public List<ReviewRecord> getReviews() {
        return Collections.unmodifiableList(reviews);
    }

    public void addReview(ReviewRecord review) {
        reviews.add(review);
        touch();
        Map<String, Object> payload = new LinkedHashMap<String, Object>();
        payload.put("reviewId", review.getReviewId());
        payload.put("decision", review.getDecision().name());
        addEvent("REVIEW_RECORDED", payload);
    }

    public List<RunEventRecord> getEvents() {
        return Collections.unmodifiableList(events);
    }

    public void addEvent(String eventType, Map<String, Object> payload) {
        events.add(new RunEventRecord(runId, eventType, payload));
        touch();
    }

    private void touch() {
        this.updatedAt = Instant.now();
    }
}
