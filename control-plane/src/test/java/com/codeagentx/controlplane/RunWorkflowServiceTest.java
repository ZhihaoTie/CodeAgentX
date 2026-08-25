package com.codeagentx.controlplane;

import com.codeagentx.controlplane.domain.InMemoryRunRepository;
import com.codeagentx.controlplane.domain.ReviewDecision;
import com.codeagentx.controlplane.domain.RunRecord;
import com.codeagentx.controlplane.domain.RunStatus;
import com.codeagentx.controlplane.domain.TaskExecutionSpec;
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
import com.codeagentx.controlplane.workflow.RunWorkflowService;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class RunWorkflowServiceTest {
    @Test
    void createTaskAndRunSubmitsRuntimeRun() {
        FakeRuntimeClient runtimeClient = new FakeRuntimeClient();
        RunWorkflowService service = new RunWorkflowService(
            new InMemoryRunRepository(),
            runtimeClient
        );

        RunRecord run = service.createTaskAndRun(
            "rest",
            "Fix failing test",
            "The calculator returns the wrong total."
        );

        assertThat(run.getStatus()).isEqualTo(RunStatus.RUNNING);
        assertThat(run.getRuntimeRunId()).isEqualTo("runtime-1");
        assertThat(runtimeClient.submittedTasks).hasSize(1);
        assertThat(runtimeClient.submittedTasks.get(0)).contains("Fix failing test");
        assertThat(run.getEvents())
            .extracting("eventType")
            .contains("RUN_CREATED", "STATUS_CHANGED", "RUNTIME_RUN_LINKED");
    }

    @Test
    void createTaskAndRunPassesExecutionSpecToRuntime() {
        FakeRuntimeClient runtimeClient = new FakeRuntimeClient();
        RunWorkflowService service = new RunWorkflowService(
            new InMemoryRunRepository(),
            runtimeClient
        );

        service.createTaskAndRun(new TaskExecutionSpec(
            "rest",
            "Fix repository bug",
            "Use the failing test as the acceptance check.",
            "task-123",
            "https://github.com/acme/repo.git",
            "acme/repo",
            "main",
            "D:\\workspaces\\repo",
            "py -3.13 -B -m pytest tests/test_bug.py"
        ));

        assertThat(runtimeClient.submittedRequests).hasSize(1);
        RuntimeRunRequest request = runtimeClient.submittedRequests.get(0);
        assertThat(request.getTask()).contains("Repository: acme/repo");
        assertThat(request.getTask()).contains("Base branch: main");
        assertThat(request.getWorkspaceRoot()).isEqualTo("D:\\workspaces\\repo");
        assertThat(request.getVerificationCommand()).isEqualTo("py -3.13 -B -m pytest tests/test_bug.py");
    }

    @Test
    void repeatedIdempotencyKeyReturnsExistingRunWithoutResubmittingRuntime() {
        FakeRuntimeClient runtimeClient = new FakeRuntimeClient();
        RunWorkflowService service = new RunWorkflowService(
            new InMemoryRunRepository(),
            runtimeClient
        );

        RunRecord first = service.createTaskAndRun(
            "github",
            "Fix duplicate webhook",
            "Delivery replayed.",
            "github-delivery-123"
        );
        RunRecord second = service.createTaskAndRun(
            "github",
            "Fix duplicate webhook",
            "Delivery replayed again.",
            "github-delivery-123"
        );

        assertThat(second.getRunId()).isEqualTo(first.getRunId());
        assertThat(runtimeClient.submittedTasks).hasSize(1);
    }

    @Test
    void refreshSucceededRuntimeRunMovesToReview() {
        FakeRuntimeClient runtimeClient = new FakeRuntimeClient();
        runtimeClient.nextStatus = "SUCCEEDED";
        runtimeClient.nextFinalText = "Patch ready.";
        runtimeClient.nextPatchDiff = "diff --git a/a.py b/a.py";
        runtimeClient.nextTestReport = "pytest passed";
        runtimeClient.nextChangedFiles = "a.py";
        runtimeClient.nextTrajectoryReportPath = "reports/run.md";
        RunWorkflowService service = new RunWorkflowService(
            new InMemoryRunRepository(),
            runtimeClient
        );
        RunRecord run = service.createTaskAndRun("rest", "Fix bug", "Details");

        RunRecord refreshed = service.refreshFromRuntime(run.getRunId());

        assertThat(refreshed.getStatus()).isEqualTo(RunStatus.NEEDS_REVIEW);
        assertThat(refreshed.getFinalText()).isEqualTo("Patch ready.");
        assertThat(refreshed.getPatchArtifact().getDiffText()).contains("diff --git");
        assertThat(refreshed.getPatchArtifact().getTestReport()).isEqualTo("pytest passed");
    }

    @Test
    void refreshSucceededRuntimeRunCanUseCollectedGitDiffArtifact() {
        FakeRuntimeClient runtimeClient = new FakeRuntimeClient();
        runtimeClient.nextStatus = "SUCCEEDED";
        runtimeClient.nextFinalText = "Patch ready.";
        RunWorkflowService service = new RunWorkflowService(
            new InMemoryRunRepository(),
            runtimeClient,
            new NoopWorkspacePreparerForTest("D:\\workspaces\\repo"),
            new FakeGitDiffCollector()
        );
        RunRecord run = service.createTaskAndRun("rest", "Fix bug", "Details");

        RunRecord refreshed = service.refreshFromRuntime(run.getRunId());

        assertThat(refreshed.getStatus()).isEqualTo(RunStatus.NEEDS_REVIEW);
        assertThat(refreshed.getPatchArtifact().getDiffText()).contains("diff --git");
        assertThat(refreshed.getPatchArtifact().getChangedFiles()).contains("app.py");
    }

    @Test
    void refreshRunningRunsMovesCompletedRuntimeRunToReview() {
        FakeRuntimeClient runtimeClient = new FakeRuntimeClient();
        runtimeClient.nextStatus = "SUCCEEDED";
        runtimeClient.nextFinalText = "Patch ready.";
        RunWorkflowService service = new RunWorkflowService(
            new InMemoryRunRepository(),
            runtimeClient
        );
        RunRecord run = service.createTaskAndRun("rest", "Fix bug", "Details");

        int refreshed = service.refreshRunningRuns();
        RunRecord loaded = service.getRun(run.getRunId());

        assertThat(refreshed).isEqualTo(1);
        assertThat(loaded.getStatus()).isEqualTo(RunStatus.NEEDS_REVIEW);
        assertThat(loaded.getFinalText()).isEqualTo("Patch ready.");
    }

    @Test
    void requestChangesRecordsReviewAndStartsRevisionRun() {
        FakeRuntimeClient runtimeClient = new FakeRuntimeClient();
        RunWorkflowService service = new RunWorkflowService(
            new InMemoryRunRepository(),
            runtimeClient
        );
        RunRecord run = service.createTaskAndRun("rest", "Fix bug", "Details");

        RunRecord reviewed = service.reviewRun(
            run.getRunId(),
            ReviewDecision.REQUEST_CHANGES,
            "Add a boundary test."
        );

        assertThat(reviewed.getStatus()).isEqualTo(RunStatus.REVISING);
        assertThat(reviewed.getReviews()).hasSize(1);
        assertThat(reviewed.getEvents())
            .extracting("eventType")
            .contains("REVIEW_RECORDED");
        assertThat(runtimeClient.submittedTasks).hasSize(2);
        assertThat(runtimeClient.submittedTasks.get(1)).contains("Add a boundary test.");
    }

    @Test
    void refreshRunningRunsPollsRevisingRunBackToReview() {
        FakeRuntimeClient runtimeClient = new FakeRuntimeClient();
        RunWorkflowService service = new RunWorkflowService(
            new InMemoryRunRepository(),
            runtimeClient
        );
        RunRecord run = service.createTaskAndRun("rest", "Fix bug", "Details");
        service.reviewRun(
            run.getRunId(),
            ReviewDecision.REQUEST_CHANGES,
            "Add a boundary test."
        );
        runtimeClient.nextStatus = "SUCCEEDED";
        runtimeClient.nextFinalText = "Revised patch ready.";
        runtimeClient.nextPatchDiff = "diff --git a/a.py b/a.py";

        int refreshed = service.refreshRunningRuns();
        RunRecord loaded = service.getRun(run.getRunId());

        assertThat(refreshed).isEqualTo(1);
        assertThat(loaded.getStatus()).isEqualTo(RunStatus.NEEDS_REVIEW);
        assertThat(loaded.getFinalText()).isEqualTo("Revised patch ready.");
        assertThat(loaded.getPatchArtifact().getDiffText()).contains("diff --git");
    }
    @Test
    void authorizePrPublishesPullRequestOnlyAfterReviewDecision() {
        FakeRuntimeClient runtimeClient = new FakeRuntimeClient();
        RunWorkflowService service = new RunWorkflowService(
            new InMemoryRunRepository(),
            runtimeClient
        );
        RunRecord run = service.createTaskAndRun("rest", "Fix bug", "Details");

        RunRecord reviewed = service.reviewRun(
            run.getRunId(),
            ReviewDecision.AUTHORIZE_PR,
            "Ship it."
        );

        assertThat(reviewed.getStatus()).isEqualTo(RunStatus.PR_CREATED);
        assertThat(reviewed.getPullRequestUrl()).startsWith("noop://pull-requests/");
        assertThat(reviewed.getPatchBranch()).isEqualTo("codeagentx/run-" + run.getRunId());
        assertThat(reviewed.getEvents())
            .extracting("eventType")
            .contains("REVIEW_RECORDED", "PATCH_BRANCH_PREPARED", "PR_CREATED");
    }

    @Test
    void authorizePrPreparesPatchBranchBeforePublishing() {
        FakeRuntimeClient runtimeClient = new FakeRuntimeClient();
        RunWorkflowService service = new RunWorkflowService(
            new InMemoryRunRepository(),
            runtimeClient,
            new NoopWorkspacePreparerForTest("D:\\workspaces\\repo"),
            new FakeGitDiffCollector(),
            new FakePatchBranchPreparer(),
            new FakePatchCommitter(),
            new FakePatchPusher()
        );
        RunRecord run = service.createTaskAndRun("rest", "Fix bug", "Details");

        RunRecord reviewed = service.reviewRun(
            run.getRunId(),
            ReviewDecision.AUTHORIZE_PR,
            "Ship it."
        );

        assertThat(reviewed.getStatus()).isEqualTo(RunStatus.PR_CREATED);
        assertThat(reviewed.getPatchBranch()).isEqualTo("codeagentx/custom-" + run.getRunId());
        assertThat(reviewed.getPatchCommitSha()).isEqualTo("0123456789012345678901234567890123456789");
        assertThat(reviewed.getPatchPushedRef()).isEqualTo("origin/codeagentx/custom-" + run.getRunId());
        assertThat(reviewed.getEvents())
            .extracting("eventType")
            .contains("PATCH_BRANCH_PREPARED", "PATCH_COMMITTED", "PATCH_PUSHED", "PR_CREATED");
    }

    @Test
    void recordCiStatusMovesRunThroughCiStatesByPatchBranch() {
        InMemoryRunRepository repository = new InMemoryRunRepository();
        FakeRuntimeClient runtimeClient = new FakeRuntimeClient();
        RunWorkflowService service = new RunWorkflowService(repository, runtimeClient);
        RunRecord run = service.createTaskAndRun("rest", "Fix bug", "Details");
        run.setPatchBranch("codeagentx/run-" + run.getRunId());
        repository.saveRun(run);

        RunRecord running = service.recordCiStatus(
            run.getPatchBranch(),
            "in_progress",
            null,
            "https://github.com/acme/repo/actions/runs/1"
        );
        assertThat(running.getStatus()).isEqualTo(RunStatus.CI_RUNNING);

        RunRecord succeeded = service.recordCiStatus(
            run.getPatchBranch(),
            "completed",
            "success",
            "https://github.com/acme/repo/actions/runs/1"
        );

        assertThat(succeeded.getStatus()).isEqualTo(RunStatus.SUCCEEDED);
        assertThat(succeeded.getFinalText()).contains("CI succeeded");
    }

    @Test
    void recordCiStatusMarksFailedConclusionAsFailed() {
        InMemoryRunRepository repository = new InMemoryRunRepository();
        FakeRuntimeClient runtimeClient = new FakeRuntimeClient();
        RunWorkflowService service = new RunWorkflowService(repository, runtimeClient);
        RunRecord run = service.createTaskAndRun("rest", "Fix bug", "Details");
        run.setPatchBranch("codeagentx/run-" + run.getRunId());
        repository.saveRun(run);

        RunRecord failed = service.recordCiStatus(
            run.getPatchBranch(),
            "completed",
            "failure",
            "https://github.com/acme/repo/actions/runs/1"
        );

        assertThat(failed.getStatus()).isEqualTo(RunStatus.FAILED);
        assertThat(failed.getFailureReason()).contains("failure");
    }

    @Test
    void recordCiStatusIsIdempotentForDuplicateWorkflowRun() {
        InMemoryRunRepository repository = new InMemoryRunRepository();
        FakeRuntimeClient runtimeClient = new FakeRuntimeClient();
        RunWorkflowService service = new RunWorkflowService(repository, runtimeClient);
        RunRecord run = service.createTaskAndRun("rest", "Fix bug", "Details");
        run.setPatchBranch("codeagentx/run-" + run.getRunId());
        repository.saveRun(run);

        service.recordCiStatus(
            run.getPatchBranch(),
            "completed",
            "success",
            "https://github.com/acme/repo/actions/runs/1"
        );
        RunRecord duplicate = service.recordCiStatus(
            run.getPatchBranch(),
            "completed",
            "success",
            "https://github.com/acme/repo/actions/runs/1"
        );

        assertThat(duplicate.getStatus()).isEqualTo(RunStatus.SUCCEEDED);
        assertThat(duplicate.getFinalText().split("CI succeeded:", -1)).hasSize(2);
    }

    @Test
    void recordCiStatusDoesNotReviveTerminalRun() {
        InMemoryRunRepository repository = new InMemoryRunRepository();
        FakeRuntimeClient runtimeClient = new FakeRuntimeClient();
        RunWorkflowService service = new RunWorkflowService(repository, runtimeClient);
        RunRecord run = service.createTaskAndRun("rest", "Fix bug", "Details");
        run.setPatchBranch("codeagentx/run-" + run.getRunId());
        run.setStatus(RunStatus.FAILED);
        run.setFailureReason("Runtime failed first");
        repository.saveRun(run);

        RunRecord ignored = service.recordCiStatus(
            run.getPatchBranch(),
            "completed",
            "success",
            "https://github.com/acme/repo/actions/runs/1"
        );

        assertThat(ignored.getStatus()).isEqualTo(RunStatus.FAILED);
        assertThat(ignored.getFailureReason()).isEqualTo("Runtime failed first");
        assertThat(ignored.getFinalText()).isNull();
    }
    @Test
    void failedRuntimeSubmissionMarksRunFailed() {
        FakeRuntimeClient runtimeClient = new FakeRuntimeClient();
        runtimeClient.failSubmit = true;
        RunWorkflowService service = new RunWorkflowService(
            new InMemoryRunRepository(),
            runtimeClient
        );

        RunRecord run = service.createTaskAndRun("rest", "Fix bug", "Details");

        assertThat(run.getStatus()).isEqualTo(RunStatus.FAILED);
        assertThat(run.getFailureReason()).contains("RuntimeException");
    }

    @Test
    void runtimeSubmissionRetriesTransientFailure() {
        FakeRuntimeClient runtimeClient = new FakeRuntimeClient();
        runtimeClient.failSubmitAttemptsRemaining = 2;
        RunWorkflowService service = new RunWorkflowService(
            new InMemoryRunRepository(),
            runtimeClient,
            30 * 60 * 1000L,
            3,
            0L
        );

        RunRecord run = service.createTaskAndRun("rest", "Fix flaky runtime", "Retry transient submit failures.");

        assertThat(run.getStatus()).isEqualTo(RunStatus.RUNNING);
        assertThat(run.getRuntimeRunId()).isEqualTo("runtime-1");
        assertThat(runtimeClient.submitAttempts).isEqualTo(3);
        assertThat(run.getEvents())
            .extracting("eventType")
            .contains("RUNTIME_SUBMIT_RETRY", "RUNTIME_RUN_LINKED");
    }

    @Test
    void failedWorkspacePreparationMarksRunFailedWithoutSubmittingRuntime() {
        FakeRuntimeClient runtimeClient = new FakeRuntimeClient();
        RunWorkflowService service = new RunWorkflowService(
            new InMemoryRunRepository(),
            runtimeClient,
            new ThrowingWorkspacePreparer()
        );

        RunRecord run = service.createTaskAndRun(new TaskExecutionSpec(
            "rest",
            "Fix bug",
            "Details",
            null,
            "https://github.com/acme/repo.git",
            "acme/repo",
            "main",
            null,
            "mvn test"
        ));

        assertThat(run.getStatus()).isEqualTo(RunStatus.FAILED);
        assertThat(run.getFailureReason()).contains("workspace unavailable");
        assertThat(runtimeClient.submittedRequests).isEmpty();
    }


    @Test
    void failTimedOutRunsMarksStuckRunningRunFailed() {
        FakeRuntimeClient runtimeClient = new FakeRuntimeClient();
        runtimeClient.nextStatus = "RUNNING";
        RunWorkflowService service = new RunWorkflowService(
            new InMemoryRunRepository(),
            runtimeClient,
            0L
        );
        RunRecord run = service.createTaskAndRun("rest", "Fix bug", "Details");

        int failed = service.failTimedOutRuns();
        RunRecord loaded = service.getRun(run.getRunId());

        assertThat(failed).isEqualTo(1);
        assertThat(loaded.getStatus()).isEqualTo(RunStatus.FAILED);
        assertThat(loaded.getFailureReason()).contains("timed out");
    }

    @Test
    void failTimedOutRunsMarksStuckRevisingRunFailed() {
        FakeRuntimeClient runtimeClient = new FakeRuntimeClient();
        runtimeClient.nextStatus = "RUNNING";
        RunWorkflowService service = new RunWorkflowService(
            new InMemoryRunRepository(),
            runtimeClient,
            0L
        );
        RunRecord run = service.createTaskAndRun("rest", "Fix bug", "Details");
        run.setStatus(RunStatus.REVISING);

        int failed = service.failTimedOutRuns();
        RunRecord loaded = service.getRun(run.getRunId());

        assertThat(failed).isEqualTo(1);
        assertThat(loaded.getStatus()).isEqualTo(RunStatus.FAILED);
        assertThat(loaded.getFailureReason()).contains("timed out");
    }

    @Test
    void recoverQueuedRunsResubmitsRunWithoutRuntimeRunId() {
        FakeRuntimeClient runtimeClient = new FakeRuntimeClient();
        InMemoryRunRepository repository = new InMemoryRunRepository();
        RunWorkflowService service = new RunWorkflowService(
            repository,
            runtimeClient
        );
        com.codeagentx.controlplane.domain.TaskRecord task = repository.saveTask(
            new com.codeagentx.controlplane.domain.TaskRecord("rest", "Recover me", "Worker crashed.")
        );
        RunRecord run = new RunRecord(task.getTaskId());
        run.setStatus(RunStatus.QUEUED);
        repository.saveRun(run);

        int recovered = service.recoverQueuedRuns();
        RunRecord loaded = service.getRun(run.getRunId());

        assertThat(recovered).isEqualTo(1);
        assertThat(loaded.getStatus()).isEqualTo(RunStatus.RUNNING);
        assertThat(loaded.getRuntimeRunId()).isEqualTo("runtime-1");
        assertThat(runtimeClient.submittedTasks).hasSize(1);
        assertThat(runtimeClient.submittedTasks.get(0)).contains("Recover me");
    }

    @Test
    void cancelRunMarksNonTerminalRunCancelled() {
        FakeRuntimeClient runtimeClient = new FakeRuntimeClient();
        RunWorkflowService service = new RunWorkflowService(
            new InMemoryRunRepository(),
            runtimeClient
        );
        RunRecord run = service.createTaskAndRun("rest", "Fix bug", "Details");

        RunRecord cancelled = service.cancelRun(run.getRunId(), "User stopped the run.");

        assertThat(cancelled.getStatus()).isEqualTo(RunStatus.CANCELLED);
        assertThat(cancelled.getFailureReason()).isEqualTo("User stopped the run.");
        assertThat(cancelled.getEvents())
            .extracting("eventType")
            .contains("RUN_CANCELLED");
    }

    @Test
    void cancelRunDoesNotChangeTerminalRun() {
        FakeRuntimeClient runtimeClient = new FakeRuntimeClient();
        runtimeClient.nextStatus = "SUCCEEDED";
        RunWorkflowService service = new RunWorkflowService(
            new InMemoryRunRepository(),
            runtimeClient
        );
        RunRecord run = service.createTaskAndRun("rest", "Fix bug", "Details");
        RunRecord reviewed = service.refreshFromRuntime(run.getRunId());
        reviewed.setPatchBranch("codeagentx/run-" + reviewed.getRunId());
        RunRecord succeeded = service.recordCiStatus(
            reviewed.getPatchBranch(),
            "completed",
            "success",
            "https://github.com/acme/repo/actions/runs/1"
        );

        RunRecord afterCancel = service.cancelRun(succeeded.getRunId(), "Too late.");

        assertThat(afterCancel.getStatus()).isEqualTo(RunStatus.SUCCEEDED);
        assertThat(afterCancel.getFailureReason()).isNull();
    }

    private static class FakeRuntimeClient extends RuntimeClient {
        private int nextRunNumber = 1;
        private boolean failSubmit = false;
        private int failSubmitAttemptsRemaining = 0;
        private int submitAttempts = 0;
        private String nextStatus = "RUNNING";
        private String nextFinalText = null;
        private String nextPatchDiff = null;
        private String nextTestReport = null;
        private String nextChangedFiles = null;
        private String nextTrajectoryReportPath = null;
        private final List<String> submittedTasks = new ArrayList<String>();
        private final List<RuntimeRunRequest> submittedRequests = new ArrayList<RuntimeRunRequest>();

        FakeRuntimeClient() {
            super("http://runtime.invalid");
        }

        @Override
        public RuntimeRunResponse submitRun(RuntimeRunRequest request) {
            submitAttempts++;
            if (failSubmitAttemptsRemaining > 0) {
                failSubmitAttemptsRemaining--;
                throw new RuntimeException("runtime unavailable");
            }
            if (failSubmit) {
                throw new RuntimeException("runtime unavailable");
            }
            submittedRequests.add(request);
            submittedTasks.add(request.getTask());
            RuntimeRunResponse response = new RuntimeRunResponse();
            response.setRunId("runtime-" + nextRunNumber++);
            response.setStatus("QUEUED");
            return response;
        }

        @Override
        public RuntimeRunResponse getRun(String runtimeRunId) {
            RuntimeRunResponse response = new RuntimeRunResponse();
            response.setRunId(runtimeRunId);
            response.setStatus(nextStatus);
            response.setFinalText(nextFinalText);
            response.setPatchDiff(nextPatchDiff);
            response.setTestReport(nextTestReport);
            response.setChangedFiles(nextChangedFiles);
            response.setTrajectoryReportPath(nextTrajectoryReportPath);
            return response;
        }
    }

    private static class ThrowingWorkspacePreparer implements WorkspacePreparer {
        @Override
        public WorkspacePreparationResult prepareWorkspace(
            com.codeagentx.controlplane.domain.TaskRecord task,
            RunRecord run
        ) {
            throw new IllegalStateException("workspace unavailable");
        }
    }

    private static class NoopWorkspacePreparerForTest implements WorkspacePreparer {
        private final String workspaceRoot;

        NoopWorkspacePreparerForTest(String workspaceRoot) {
            this.workspaceRoot = workspaceRoot;
        }

        @Override
        public WorkspacePreparationResult prepareWorkspace(
            com.codeagentx.controlplane.domain.TaskRecord task,
            RunRecord run
        ) {
            return new WorkspacePreparationResult(workspaceRoot, "test workspace");
        }
    }

    private static class FakeGitDiffCollector implements GitDiffCollector {
        @Override
        public com.codeagentx.controlplane.domain.PatchArtifact collect(
            RunRecord run,
            com.codeagentx.controlplane.domain.PatchArtifact runtimeArtifact
        ) {
            return new com.codeagentx.controlplane.domain.PatchArtifact(
                "diff --git a/app.py b/app.py",
                runtimeArtifact == null ? null : runtimeArtifact.getTestReport(),
                " M app.py",
                runtimeArtifact == null ? null : runtimeArtifact.getTrajectoryReportPath()
            );
        }
    }

    private static class FakePatchBranchPreparer implements PatchBranchPreparer {
        @Override
        public PatchBranchPreparationResult preparePatchBranch(RunRecord run) {
            return new PatchBranchPreparationResult(
                "codeagentx/custom-" + run.getRunId(),
                "test patch branch"
            );
        }
    }

    private static class FakePatchCommitter implements PatchCommitter {
        @Override
        public PatchCommitResult commitPatch(RunRecord run) {
            return new PatchCommitResult(
                "0123456789012345678901234567890123456789",
                "test patch commit"
            );
        }
    }

    private static class FakePatchPusher implements PatchPusher {
        @Override
        public PatchPushResult pushPatch(RunRecord run) {
            return new PatchPushResult("origin/" + run.getPatchBranch(), "test patch push");
        }
    }
}
