package com.codeagentx.controlplane;

import com.codeagentx.controlplane.domain.ReviewDecision;
import com.codeagentx.controlplane.domain.ReviewRecord;
import com.codeagentx.controlplane.domain.PatchArtifact;
import com.codeagentx.controlplane.domain.RunRecord;
import com.codeagentx.controlplane.domain.RunStatus;
import com.codeagentx.controlplane.domain.TaskRecord;
import com.codeagentx.controlplane.domain.jpa.JpaRunRepository;
import com.codeagentx.controlplane.domain.jpa.JpaRunRecordRepository;
import com.codeagentx.controlplane.domain.jpa.JpaTaskRepository;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;
import org.springframework.context.annotation.Import;

import static org.assertj.core.api.Assertions.assertThat;

@DataJpaTest
@Import(JpaRunRepository.class)
class JpaRunRepositoryTest {
    @Autowired
    private JpaRunRepository repository;

    @Autowired
    private JpaTaskRepository taskRepository;

    @Autowired
    private JpaRunRecordRepository runRecordRepository;

    @Test
    void persistsTaskRunReviewsAndEvents() {
        TaskRecord task = repository.saveTask(
            new TaskRecord("rest", "Fix bug", "Details")
        );
        RunRecord run = new RunRecord(task.getTaskId());
        run.setStatus(RunStatus.RUNNING);
        run.setRuntimeRunId("runtime-1");
        run.setExecutionWorkspaceRoot("D:\\workspaces\\repo");
        run.setPatchBranch("codeagentx/run-123");
        run.setPatchCommitSha("0123456789012345678901234567890123456789");
        run.setPatchPushedRef("origin/codeagentx/run-123");
        run.setPullRequestUrl("noop://pull-requests/1");
        run.setPatchArtifact(new PatchArtifact("diff --git a/a b/a", "pytest passed", "a.py", "reports/run.md"));
        run.addReview(new ReviewRecord(
            run.getRunId(),
            ReviewDecision.REQUEST_CHANGES,
            "Add a boundary test."
        ));

        repository.saveRun(run);

        RunRecord loaded = repository.getRun(run.getRunId());
        RunRecord loadedByPatchBranch = repository.getRunByPatchBranch("codeagentx/run-123");

        assertThat(taskRepository.findById(task.getTaskId())).isPresent();
        assertThat(runRecordRepository.findById(run.getRunId())).isPresent();
        assertThat(loaded.getStatus()).isEqualTo(RunStatus.RUNNING);
        assertThat(loaded.getRuntimeRunId()).isEqualTo("runtime-1");
        assertThat(loaded.getExecutionWorkspaceRoot()).isEqualTo("D:\\workspaces\\repo");
        assertThat(loaded.getPatchBranch()).isEqualTo("codeagentx/run-123");
        assertThat(loaded.getPatchCommitSha()).isEqualTo("0123456789012345678901234567890123456789");
        assertThat(loaded.getPatchPushedRef()).isEqualTo("origin/codeagentx/run-123");
        assertThat(loadedByPatchBranch.getRunId()).isEqualTo(run.getRunId());
        assertThat(loaded.getPullRequestUrl()).isEqualTo("noop://pull-requests/1");
        assertThat(loaded.getPatchArtifact().getDiffText()).contains("diff --git");
        assertThat(loaded.getPatchArtifact().getTestReport()).contains("pytest");
        assertThat(loaded.getPatchArtifact().getChangedFiles()).isEqualTo("a.py");
        assertThat(loaded.getPatchArtifact().getTrajectoryReportPath()).isEqualTo("reports/run.md");
        assertThat(loaded.getReviews()).hasSize(1);
        assertThat(loaded.getEvents())
            .extracting("eventType")
            .contains("RUN_CREATED", "STATUS_CHANGED", "RUNTIME_RUN_LINKED", "REVIEW_RECORDED");
    }

    @Test
    void findsTaskAndRunByIdempotencyKey() {
        TaskRecord task = repository.saveTask(
            new TaskRecord(
                "github",
                "Webhook",
                "Details",
                "delivery-abc",
                "https://github.com/acme/repo.git",
                "acme/repo",
                "main",
                "D:\\workspaces\\repo",
                "mvn test",
                "ticket-42",
                "https://example.com/callbacks/42"
            )
        );
        RunRecord run = repository.saveRun(new RunRecord(task.getTaskId()));

        TaskRecord loadedTask = repository.getTaskByIdempotencyKey("delivery-abc");
        RunRecord loadedRun = repository.getRunByTaskId(task.getTaskId());

        assertThat(loadedTask.getTaskId()).isEqualTo(task.getTaskId());
        assertThat(loadedTask.getIdempotencyKey()).isEqualTo("delivery-abc");
        assertThat(loadedTask.getRepositoryUrl()).isEqualTo("https://github.com/acme/repo.git");
        assertThat(loadedTask.getRepositoryFullName()).isEqualTo("acme/repo");
        assertThat(loadedTask.getBaseBranch()).isEqualTo("main");
        assertThat(loadedTask.getWorkspaceRoot()).isEqualTo("D:\\workspaces\\repo");
        assertThat(loadedTask.getVerificationCommand()).isEqualTo("mvn test");
        assertThat(loadedTask.getExternalTaskId()).isEqualTo("ticket-42");
        assertThat(loadedTask.getResultCallbackUrl()).isEqualTo("https://example.com/callbacks/42");
        assertThat(loadedRun.getRunId()).isEqualTo(run.getRunId());
    }
}
