package com.codeagentx.controlplane;

import com.codeagentx.controlplane.api.RunArtifactMapper;
import com.codeagentx.controlplane.domain.PatchArtifact;
import com.codeagentx.controlplane.domain.RunRecord;
import com.codeagentx.controlplane.domain.RunStatus;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class RunArtifactMapperTest {
    @Test
    void mapsPatchArtifactAndPublicationMetadata() {
        RunRecord run = new RunRecord("task-1");
        run.setStatus(RunStatus.PR_CREATED);
        run.setPatchArtifact(new PatchArtifact(
            "diff --git a/app.py b/app.py",
            "pytest passed",
            "app.py",
            "reports/run.md"
        ));
        run.setPatchBranch("codeagentx/run-1");
        run.setPatchCommitSha("0123456789012345678901234567890123456789");
        run.setPatchPushedRef("origin/codeagentx/run-1");
        run.setPullRequestUrl("noop://pull-requests/1");

        Map<String, Object> artifact = new RunArtifactMapper().toArtifact(run);

        assertThat(artifact)
            .containsEntry("runId", run.getRunId())
            .containsEntry("taskId", "task-1")
            .containsEntry("status", "PR_CREATED")
            .containsEntry("diffText", "diff --git a/app.py b/app.py")
            .containsEntry("testReport", "pytest passed")
            .containsEntry("changedFiles", "app.py")
            .containsEntry("trajectoryReportPath", "reports/run.md")
            .containsEntry("patchBranch", "codeagentx/run-1")
            .containsEntry("patchCommitSha", "0123456789012345678901234567890123456789")
            .containsEntry("patchPushedRef", "origin/codeagentx/run-1")
            .containsEntry("pullRequestUrl", "noop://pull-requests/1");
    }
}
