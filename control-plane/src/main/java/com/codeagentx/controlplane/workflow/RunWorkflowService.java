package com.codeagentx.controlplane.workflow;

import com.codeagentx.controlplane.domain.ReviewDecision;
import com.codeagentx.controlplane.domain.ReviewRecord;
import com.codeagentx.controlplane.domain.PatchArtifact;
import com.codeagentx.controlplane.domain.RunRepositoryPort;
import com.codeagentx.controlplane.domain.RunRecord;
import com.codeagentx.controlplane.domain.RunStatus;
import com.codeagentx.controlplane.domain.TaskRecord;
import com.codeagentx.controlplane.domain.TaskExecutionSpec;
import com.codeagentx.controlplane.events.RunEventStreamHub;
import com.codeagentx.controlplane.publisher.PublishResult;
import com.codeagentx.controlplane.publisher.ResultPublisher;
import com.codeagentx.controlplane.runtime.RuntimeClient;
import com.codeagentx.controlplane.runtime.RuntimeRunRequest;
import com.codeagentx.controlplane.runtime.RuntimeRunResponse;
import com.codeagentx.controlplane.workspace.WorkspacePreparationResult;
import com.codeagentx.controlplane.workspace.WorkspacePreparer;
import com.codeagentx.controlplane.workspace.GitDiffCollector;
import com.codeagentx.controlplane.workspace.PatchBranchPreparationResult;
import com.codeagentx.controlplane.workspace.PatchBranchPreparer;
import com.codeagentx.controlplane.workspace.PatchCommitResult;
import com.codeagentx.controlplane.workspace.PatchCommitter;
import com.codeagentx.controlplane.workspace.PatchPushResult;
import com.codeagentx.controlplane.workspace.PatchPusher;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.task.TaskExecutor;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.Instant;
import java.util.Collections;

@Service
public class RunWorkflowService {
    private final RunRepositoryPort repository;
    private final RuntimeClient runtimeClient;
    private final RunEventStreamHub eventStreamHub;
    private final TaskExecutor runExecutor;
    private final Duration runTimeout;
    private final int runtimeSubmitMaxAttempts;
    private final Duration runtimeSubmitRetryBackoff;
    private final ResultPublisher resultPublisher;
    private final WorkspacePreparer workspacePreparer;
    private final GitDiffCollector gitDiffCollector;
    private final PatchBranchPreparer patchBranchPreparer;
    private final PatchCommitter patchCommitter;
    private final PatchPusher patchPusher;

    public RunWorkflowService(RunRepositoryPort repository, RuntimeClient runtimeClient) {
        this(repository, runtimeClient, new RunEventStreamHub(), new DirectTaskExecutor(), 30 * 60 * 1000L, 1, 0L, new NoopTestResultPublisher(), new NoopWorkspacePreparer(), new NoopGitDiffCollector(), new NoopPatchBranchPreparer(), new NoopPatchCommitter(), new NoopPatchPusher());
    }

    public RunWorkflowService(RunRepositoryPort repository, RuntimeClient runtimeClient, long runTimeoutMs) {
        this(repository, runtimeClient, new RunEventStreamHub(), new DirectTaskExecutor(), runTimeoutMs, 1, 0L, new NoopTestResultPublisher(), new NoopWorkspacePreparer(), new NoopGitDiffCollector(), new NoopPatchBranchPreparer(), new NoopPatchCommitter(), new NoopPatchPusher());
    }

    public RunWorkflowService(RunRepositoryPort repository, RuntimeClient runtimeClient, long runTimeoutMs, int runtimeSubmitMaxAttempts, long runtimeSubmitRetryBackoffMs) {
        this(repository, runtimeClient, new RunEventStreamHub(), new DirectTaskExecutor(), runTimeoutMs, runtimeSubmitMaxAttempts, runtimeSubmitRetryBackoffMs, new NoopTestResultPublisher(), new NoopWorkspacePreparer(), new NoopGitDiffCollector(), new NoopPatchBranchPreparer(), new NoopPatchCommitter(), new NoopPatchPusher());
    }

    public RunWorkflowService(
        RunRepositoryPort repository,
        RuntimeClient runtimeClient,
        WorkspacePreparer workspacePreparer
    ) {
        this(repository, runtimeClient, new RunEventStreamHub(), new DirectTaskExecutor(), 30 * 60 * 1000L, 1, 0L, new NoopTestResultPublisher(), workspacePreparer, new NoopGitDiffCollector(), new NoopPatchBranchPreparer(), new NoopPatchCommitter(), new NoopPatchPusher());
    }

    public RunWorkflowService(
        RunRepositoryPort repository,
        RuntimeClient runtimeClient,
        WorkspacePreparer workspacePreparer,
        GitDiffCollector gitDiffCollector
    ) {
        this(repository, runtimeClient, new RunEventStreamHub(), new DirectTaskExecutor(), 30 * 60 * 1000L, 1, 0L, new NoopTestResultPublisher(), workspacePreparer, gitDiffCollector, new NoopPatchBranchPreparer(), new NoopPatchCommitter(), new NoopPatchPusher());
    }

    public RunWorkflowService(
        RunRepositoryPort repository,
        RuntimeClient runtimeClient,
        WorkspacePreparer workspacePreparer,
        GitDiffCollector gitDiffCollector,
        PatchBranchPreparer patchBranchPreparer
    ) {
        this(repository, runtimeClient, new RunEventStreamHub(), new DirectTaskExecutor(), 30 * 60 * 1000L, 1, 0L, new NoopTestResultPublisher(), workspacePreparer, gitDiffCollector, patchBranchPreparer, new NoopPatchCommitter(), new NoopPatchPusher());
    }

    public RunWorkflowService(
        RunRepositoryPort repository,
        RuntimeClient runtimeClient,
        WorkspacePreparer workspacePreparer,
        GitDiffCollector gitDiffCollector,
        PatchBranchPreparer patchBranchPreparer,
        PatchCommitter patchCommitter
    ) {
        this(repository, runtimeClient, new RunEventStreamHub(), new DirectTaskExecutor(), 30 * 60 * 1000L, 1, 0L, new NoopTestResultPublisher(), workspacePreparer, gitDiffCollector, patchBranchPreparer, patchCommitter, new NoopPatchPusher());
    }

    public RunWorkflowService(
        RunRepositoryPort repository,
        RuntimeClient runtimeClient,
        WorkspacePreparer workspacePreparer,
        GitDiffCollector gitDiffCollector,
        PatchBranchPreparer patchBranchPreparer,
        PatchCommitter patchCommitter,
        PatchPusher patchPusher
    ) {
        this(repository, runtimeClient, new RunEventStreamHub(), new DirectTaskExecutor(), 30 * 60 * 1000L, 1, 0L, new NoopTestResultPublisher(), workspacePreparer, gitDiffCollector, patchBranchPreparer, patchCommitter, patchPusher);
    }

    @Autowired
    public RunWorkflowService(
        RunRepositoryPort repository,
        RuntimeClient runtimeClient,
        RunEventStreamHub eventStreamHub,
        @Qualifier("agentRunExecutor") TaskExecutor runExecutor,
        @Value("${codeagentx.runtime.run-timeout-ms:1800000}") long runTimeoutMs,
        @Value("${codeagentx.runtime.submit-max-attempts:1}") int runtimeSubmitMaxAttempts,
        @Value("${codeagentx.runtime.submit-retry-backoff-ms:0}") long runtimeSubmitRetryBackoffMs,
        ResultPublisher resultPublisher,
        WorkspacePreparer workspacePreparer,
        GitDiffCollector gitDiffCollector,
        PatchBranchPreparer patchBranchPreparer,
        PatchCommitter patchCommitter,
        PatchPusher patchPusher
    ) {
        this.repository = repository;
        this.runtimeClient = runtimeClient;
        this.eventStreamHub = eventStreamHub;
        this.runExecutor = runExecutor;
        this.runTimeout = Duration.ofMillis(runTimeoutMs);
        this.runtimeSubmitMaxAttempts = Math.max(1, runtimeSubmitMaxAttempts);
        this.runtimeSubmitRetryBackoff = Duration.ofMillis(Math.max(0L, runtimeSubmitRetryBackoffMs));
        this.resultPublisher = resultPublisher;
        this.workspacePreparer = workspacePreparer;
        this.gitDiffCollector = gitDiffCollector;
        this.patchBranchPreparer = patchBranchPreparer;
        this.patchCommitter = patchCommitter;
        this.patchPusher = patchPusher;
    }

    public RunRecord createTaskAndRun(String source, String title, String body) {
        return createTaskAndRun(source, title, body, null);
    }

    public RunRecord createTaskAndRun(String source, String title, String body, String idempotencyKey) {
        return createTaskAndRun(new TaskExecutionSpec(
            source, title, body, idempotencyKey, null, null, null, null, null
        ));
    }

    public RunRecord createTaskAndRun(TaskExecutionSpec spec) {
        TaskRecord existingTask = repository.getTaskByIdempotencyKey(spec.getIdempotencyKey());
        if (existingTask != null) {
            RunRecord existingRun = repository.getRunByTaskId(existingTask.getTaskId());
            if (existingRun != null) {
                return existingRun;
            }
        }

        TaskRecord task = repository.saveTask(new TaskRecord(
            spec.getSource(),
            spec.getTitle(),
            spec.getBody(),
            spec.getIdempotencyKey(),
            spec.getRepositoryUrl(),
            spec.getRepositoryFullName(),
            spec.getBaseBranch(),
            spec.getWorkspaceRoot(),
            spec.getVerificationCommand(),
            spec.getExternalTaskId(),
            spec.getResultCallbackUrl()
        ));
        RunRecord run = new RunRecord(task.getTaskId());
        run.setStatus(RunStatus.QUEUED);
        saveAndPublish(run);
        submitRuntimeRunAsync(run.getRunId(), taskText(task));
        return run;
    }

    public RunRecord getRun(String runId) {
        return repository.getRun(runId);
    }

    public RunRecord reviewRun(String runId, ReviewDecision decision, String comment) {
        RunRecord run = requireRun(runId);
        if (isTerminal(run.getStatus())) {
            return run;
        }

        if (decision == ReviewDecision.AUTHORIZE_PR) {
            requireReviewState(run, RunStatus.APPROVED, decision);
        } else {
            requireReviewState(run, RunStatus.NEEDS_REVIEW, decision);
        }

        ReviewRecord review = new ReviewRecord(runId, decision, comment);
        run.addReview(review);

        if (decision == ReviewDecision.APPROVE) {
            run.setStatus(RunStatus.APPROVED);
        } else if (decision == ReviewDecision.REQUEST_CHANGES) {
            run.setStatus(RunStatus.CHANGES_REQUESTED);
            saveAndPublish(run);
            TaskRecord task = repository.getTask(run.getTaskId());
            submitRuntimeRunAsync(run.getRunId(), taskText(task) + "\n\nReview requested changes:\n" + comment);
            return requireRun(runId);
        } else if (decision == ReviewDecision.REJECT) {
            run.setStatus(RunStatus.CANCELLED);
        } else if (decision == ReviewDecision.AUTHORIZE_PR) {
            run.setStatus(RunStatus.PR_CREATING);
            saveAndPublish(run);
            return publishPullRequest(run.getRunId());
        }

        return saveAndPublish(run);
    }

    private void requireReviewState(RunRecord run, RunStatus expectedStatus, ReviewDecision decision) {
        if (run.getStatus() != expectedStatus) {
            throw new InvalidRunStateException(
                "Review decision " + decision.name() + " requires run status " + expectedStatus.name()
                    + " but was " + run.getStatus().name()
            );
        }
    }

    public RunRecord cancelRun(String runId, String reason) {
        RunRecord run = requireRun(runId);
        if (isTerminal(run.getStatus())) {
            return run;
        }
        run.setStatus(RunStatus.CANCELLED);
        run.setFailureReason(reason == null || reason.trim().isEmpty()
            ? "Run cancelled by control plane"
            : reason.trim()
        );
        run.addEvent("RUN_CANCELLED", Collections.<String, Object>singletonMap(
            "reason",
            run.getFailureReason()
        ));
        return saveAndPublish(run);
    }

    public void submitRuntimeRun(String runId, String taskText) {
        RunRecord run = requireRun(runId);
        if (run.getStatus() == RunStatus.CANCELLED) {
            return;
        }
        boolean revisionRun = run.getStatus() == RunStatus.CHANGES_REQUESTED || run.getStatus() == RunStatus.REVISING;
        if (revisionRun) {
            run.setStatus(RunStatus.REVISING);
        } else {
            run.setStatus(RunStatus.QUEUED);
        }
        try {
            RuntimeRunRequest request = new RuntimeRunRequest(taskText);
            TaskRecord task = repository.getTask(run.getTaskId());
            if (task != null) {
                WorkspacePreparationResult workspace = workspacePreparer.prepareWorkspace(task, run);
                request.setWorkspaceRoot(workspace.getWorkspaceRoot());
                if (workspace.getWorkspaceRoot() != null) {
                    run.setExecutionWorkspaceRoot(workspace.getWorkspaceRoot());
                }
                request.setVerificationCommand(task.getVerificationCommand());
            }
            RuntimeRunResponse response = submitRunWithRetry(run, request);
            if (response != null) {
                run.setRuntimeRunId(response.getRunId());
            }
            run.setStatus(revisionRun ? RunStatus.REVISING : RunStatus.RUNNING);
        } catch (Exception exc) {
            run.setStatus(RunStatus.FAILED);
            run.setFailureReason(exc.getClass().getSimpleName() + ": " + exc.getMessage());
        }
        saveAndPublish(run);
    }

    private RuntimeRunResponse submitRunWithRetry(RunRecord run, RuntimeRunRequest request) {
        RuntimeException lastFailure = null;
        for (int attempt = 1; attempt <= runtimeSubmitMaxAttempts; attempt++) {
            try {
                return runtimeClient.submitRun(request);
            } catch (RuntimeException exc) {
                lastFailure = exc;
                if (attempt >= runtimeSubmitMaxAttempts) {
                    throw exc;
                }
                run.addEvent("RUNTIME_SUBMIT_RETRY", Collections.<String, Object>singletonMap(
                    "attempt",
                    attempt
                ));
                sleepBeforeRetry();
            }
        }
        throw lastFailure == null ? new IllegalStateException("runtime submission failed") : lastFailure;
    }

    private void sleepBeforeRetry() {
        if (runtimeSubmitRetryBackoff.isZero() || runtimeSubmitRetryBackoff.isNegative()) {
            return;
        }
        try {
            Thread.sleep(runtimeSubmitRetryBackoff.toMillis());
        } catch (InterruptedException exc) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("runtime submission retry interrupted", exc);
        }
    }

    public void submitRuntimeRunAsync(final String runId, final String taskText) {
        runExecutor.execute(new Runnable() {
            @Override
            public void run() {
                submitRuntimeRun(runId, taskText);
            }
        });
    }

    public RunRecord refreshFromRuntime(String runId) {
        RunRecord run = requireRun(runId);
        if (run.getRuntimeRunId() == null) {
            return run;
        }
        RuntimeRunResponse response = runtimeClient.getRun(run.getRuntimeRunId());
        if (response == null) {
            return run;
        }
        if ("SUCCEEDED".equals(response.getStatus())) {
            run.setFinalText(response.getFinalText());
            run.setPatchArtifact(collectPatchArtifact(run, response.toPatchArtifact()));
            run.setStatus(RunStatus.NEEDS_REVIEW);
        } else if ("FAILED".equals(response.getStatus())) {
            run.setFinalText(response.getFinalText());
            run.setPatchArtifact(collectPatchArtifact(run, response.toPatchArtifact()));
            run.setStatus(RunStatus.FAILED);
            run.setFailureReason(response.getError());
        } else if ("RUNNING".equals(response.getStatus())) {
            run.setStatus(run.getStatus() == RunStatus.REVISING ? RunStatus.REVISING : RunStatus.RUNNING);
        }
        return saveAndPublish(run);
    }

    public int refreshRunningRuns() {
        int refreshed = 0;
        for (RunStatus status : new RunStatus[] {RunStatus.RUNNING, RunStatus.REVISING}) {
            for (RunRecord run : repository.listRunsByStatus(status)) {
                if (run.getRuntimeRunId() != null) {
                    refreshFromRuntime(run.getRunId());
                    refreshed++;
                }
            }
        }
        return refreshed;
    }

    public int failTimedOutRuns() {
        int failed = 0;
        Instant now = Instant.now();
        for (RunStatus status : new RunStatus[] {RunStatus.RUNNING, RunStatus.REVISING}) {
            for (RunRecord run : repository.listRunsByStatus(status)) {
                if (run.isTimedOut(now, runTimeout)) {
                    run.setStatus(RunStatus.FAILED);
                    run.setFailureReason("Run timed out after " + runTimeout.toMillis() + " ms");
                    saveAndPublish(run);
                    failed++;
                }
            }
        }
        return failed;
    }

    public int recoverQueuedRuns() {
        int recovered = 0;
        for (RunRecord run : repository.listRunsByStatus(RunStatus.QUEUED)) {
            if (run.getRuntimeRunId() == null) {
                TaskRecord task = repository.getTask(run.getTaskId());
                if (task != null) {
                    submitRuntimeRunAsync(
                        run.getRunId(),
                        taskText(task)
                    );
                    recovered++;
                }
            }
        }
        return recovered;
    }

    public RunRecord publishPullRequest(String runId) {
        RunRecord run = requireRun(runId);
        try {
            TaskRecord task = repository.getTask(run.getTaskId());
            PatchBranchPreparationResult branch = patchBranchPreparer.preparePatchBranch(run);
            if (branch.getBranchName() != null) {
                run.setPatchBranch(branch.getBranchName());
            }
            PatchCommitResult commit = patchCommitter.commitPatch(run);
            if (commit.getCommitSha() != null) {
                run.setPatchCommitSha(commit.getCommitSha());
            }
            PatchPushResult push = patchPusher.pushPatch(run);
            if (push.getPushedRef() != null) {
                run.setPatchPushedRef(push.getPushedRef());
            }
            PublishResult result = resultPublisher.publishPullRequest(run, task);
            run.setPullRequestUrl(result.getPullRequestUrl());
            run.setStatus(RunStatus.PR_CREATED);
        } catch (Exception exc) {
            run.setStatus(RunStatus.FAILED);
            run.setFailureReason(exc.getClass().getSimpleName() + ": " + exc.getMessage());
        }
        return saveAndPublish(run);
    }

    public RunRecord recordCiStatus(String patchBranch, String status, String conclusion, String url) {
        RunRecord run = repository.getRunByPatchBranch(patchBranch);
        if (run == null) {
            return null;
        }

        if (isTerminal(run.getStatus())) {
            return run;
        }

        if ("completed".equals(status)) {
            if ("success".equals(conclusion)) {
                run.setStatus(RunStatus.SUCCEEDED);
                run.setFinalText(appendLineIfMissing(run.getFinalText(), "CI succeeded: " + nullToEmpty(url)));
            } else {
                run.setStatus(RunStatus.FAILED);
                run.setFailureReason("CI failed with conclusion: " + nullToEmpty(conclusion));
                run.setFinalText(appendLineIfMissing(run.getFinalText(), "CI failed: " + nullToEmpty(url)));
            }
        } else {
            run.setStatus(RunStatus.CI_RUNNING);
            run.setFinalText(appendLineIfMissing(run.getFinalText(), "CI status: " + nullToEmpty(status) + " " + nullToEmpty(url)));
        }
        return saveAndPublish(run);
    }

    private RunRecord requireRun(String runId) {
        RunRecord run = repository.getRun(runId);
        if (run == null) {
            throw new IllegalArgumentException("run not found: " + runId);
        }
        return run;
    }

    private RunRecord saveAndPublish(RunRecord run) {
        RunRecord saved = repository.saveRun(run);
        eventStreamHub.publish(saved);
        return saved;
    }

    private boolean isTerminal(RunStatus status) {
        return status == RunStatus.SUCCEEDED
            || status == RunStatus.FAILED
            || status == RunStatus.CANCELLED;
    }

    private PatchArtifact collectPatchArtifact(RunRecord run, PatchArtifact runtimeArtifact) {
        try {
            return gitDiffCollector.collect(run, runtimeArtifact);
        } catch (Exception exc) {
            return runtimeArtifact;
        }
    }

    private String taskText(TaskRecord task) {
        StringBuilder text = new StringBuilder();
        text.append(task.getTitle()).append("\n\n").append(task.getBody());
        if (task.getRepositoryFullName() != null) {
            text.append("\n\nRepository: ").append(task.getRepositoryFullName());
        }
        if (task.getBaseBranch() != null) {
            text.append("\nBase branch: ").append(task.getBaseBranch());
        }
        return text.toString();
    }

    private String appendLineIfMissing(String value, String line) {
        if (line == null || line.trim().isEmpty()) {
            return value;
        }
        if (value != null) {
            String[] lines = value.split("\\R");
            for (String existing : lines) {
                if (line.equals(existing)) {
                    return value;
                }
            }
        }
        return appendLine(value, line);
    }
    private String appendLine(String value, String line) {
        if (line == null || line.trim().isEmpty()) {
            return value;
        }
        if (value == null || value.trim().isEmpty()) {
            return line;
        }
        return value + "\n" + line;
    }

    private String nullToEmpty(String value) {
        return value == null ? "" : value;
    }

    private static class DirectTaskExecutor implements TaskExecutor {
        @Override
        public void execute(Runnable task) {
            task.run();
        }
    }

    private static class NoopTestResultPublisher implements ResultPublisher {
        @Override
        public PublishResult publishPullRequest(RunRecord run, TaskRecord task) {
            return new PublishResult("noop://pull-requests/" + run.getRunId());
        }
    }

    private static class NoopWorkspacePreparer implements WorkspacePreparer {
        @Override
        public WorkspacePreparationResult prepareWorkspace(TaskRecord task, RunRecord run) {
            return new WorkspacePreparationResult(task.getWorkspaceRoot(), "noop workspace preparation");
        }
    }

    private static class NoopGitDiffCollector implements GitDiffCollector {
        @Override
        public PatchArtifact collect(RunRecord run, PatchArtifact runtimeArtifact) {
            return runtimeArtifact;
        }
    }

    private static class NoopPatchBranchPreparer implements PatchBranchPreparer {
        @Override
        public PatchBranchPreparationResult preparePatchBranch(RunRecord run) {
            return new PatchBranchPreparationResult("codeagentx/run-" + run.getRunId(), "noop patch branch preparation");
        }
    }

    private static class NoopPatchCommitter implements PatchCommitter {
        @Override
        public PatchCommitResult commitPatch(RunRecord run) {
            return new PatchCommitResult(null, "noop patch commit");
        }
    }

    private static class NoopPatchPusher implements PatchPusher {
        @Override
        public PatchPushResult pushPatch(RunRecord run) {
            return new PatchPushResult(null, "noop patch push");
        }
    }
}
