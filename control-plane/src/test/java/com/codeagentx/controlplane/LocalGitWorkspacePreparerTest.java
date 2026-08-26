package com.codeagentx.controlplane;

import com.codeagentx.controlplane.domain.RunRecord;
import com.codeagentx.controlplane.domain.TaskRecord;
import com.codeagentx.controlplane.workspace.LocalGitWorkspacePreparer;
import com.codeagentx.controlplane.workspace.WorkspacePreparationResult;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermission;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

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

    @Test
    void preparesManagedWorkspaceWithSharedWritePermissions() throws Exception {
        assumeTrue(hasPosixPermissions(tempDir));
        assumeTrue(run(tempDir, "git", "--version").exitCode == 0);

        Path source = tempDir.resolve("source");
        Files.createDirectories(source);
        run(source, "git", "init");
        run(source, "git", "checkout", "-b", "main");
        run(source, "git", "config", "user.email", "codeagentx@example.com");
        run(source, "git", "config", "user.name", "CodeAgent-X Test");
        Files.write(source.resolve("app.py"), "value = 1\n".getBytes(java.nio.charset.StandardCharsets.UTF_8));
        run(source, "git", "add", "app.py");
        run(source, "git", "commit", "-m", "initial");

        Path managedRoot = tempDir.resolve("managed-workspaces");
        LocalGitWorkspacePreparer preparer = new LocalGitWorkspacePreparer(managedRoot.toString());
        TaskRecord task = new TaskRecord(
            "github",
            "Fix bug",
            "Details",
            source.toUri().toString(),
            "owner/repo",
            "main",
            null,
            null,
            "mvn test"
        );
        RunRecord run = new RunRecord(task.getTaskId());

        WorkspacePreparationResult result = preparer.prepareWorkspace(task, run);

        Path workspace = Path.of(result.getWorkspaceRoot());
        assertThat(Files.getPosixFilePermissions(workspace))
            .contains(PosixFilePermission.OTHERS_READ)
            .contains(PosixFilePermission.OTHERS_WRITE)
            .contains(PosixFilePermission.OTHERS_EXECUTE);
        assertThat(Files.getPosixFilePermissions(workspace.resolve("app.py")))
            .contains(PosixFilePermission.OTHERS_READ)
            .contains(PosixFilePermission.OTHERS_WRITE);
    }

    private boolean hasPosixPermissions(Path path) {
        try {
            Files.getPosixFilePermissions(path);
            return true;
        } catch (UnsupportedOperationException exc) {
            return false;
        } catch (Exception exc) {
            return false;
        }
    }

    private CommandResult run(Path cwd, String... command) throws Exception {
        ProcessBuilder builder = new ProcessBuilder(command);
        builder.directory(cwd.toFile());
        builder.redirectErrorStream(true);
        Process process = builder.start();
        java.io.ByteArrayOutputStream output = new java.io.ByteArrayOutputStream();
        process.getInputStream().transferTo(output);
        int exitCode = process.waitFor();
        return new CommandResult(exitCode, output.toString(java.nio.charset.StandardCharsets.UTF_8).trim());
    }

    private static class CommandResult {
        private final int exitCode;

        private CommandResult(int exitCode, String output) {
            this.exitCode = exitCode;
        }
    }
}
