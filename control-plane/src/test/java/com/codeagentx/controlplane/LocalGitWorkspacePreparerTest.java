package com.codeagentx.controlplane;

import com.codeagentx.controlplane.domain.RunRecord;
import com.codeagentx.controlplane.domain.TaskRecord;
import com.codeagentx.controlplane.workspace.LocalGitWorkspacePreparer;
import com.codeagentx.controlplane.workspace.WorkspacePreparationResult;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class LocalGitWorkspacePreparerTest {
    @TempDir
    Path tempDir;

    @Test
    void usesExplicitWorkspaceRootWhenProvided() {
        LocalGitWorkspacePreparer preparer = new LocalGitWorkspacePreparer(
            tempDir.resolve("managed-workspaces").toString()
        );
        TaskRecord task = new TaskRecord(
            "rest",
            "Fix bug",
            "Details",
            null,
            null,
            null,
            null,
            tempDir.toString(),
            "mvn test"
        );
        RunRecord run = new RunRecord(task.getTaskId());

        WorkspacePreparationResult result = preparer.prepareWorkspace(task, run);

        assertThat(result.getWorkspaceRoot()).isEqualTo(tempDir.toAbsolutePath().normalize().toString());
        assertThat(result.getDetail()).contains("explicit");
    }

    @Test
    void rejectsMissingExplicitWorkspaceRoot() {
        LocalGitWorkspacePreparer preparer = new LocalGitWorkspacePreparer(
            tempDir.resolve("managed-workspaces").toString()
        );
        TaskRecord task = new TaskRecord(
            "rest",
            "Fix bug",
            "Details",
            null,
            null,
            null,
            null,
            tempDir.resolve("missing").toString(),
            "mvn test"
        );
        RunRecord run = new RunRecord(task.getTaskId());

        assertThatThrownBy(() -> preparer.prepareWorkspace(task, run))
            .isInstanceOf(IllegalStateException.class)
            .hasMessageContaining("workspace root does not exist");
    }
}
