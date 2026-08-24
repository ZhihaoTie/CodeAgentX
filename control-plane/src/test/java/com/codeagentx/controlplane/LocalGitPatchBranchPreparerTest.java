package com.codeagentx.controlplane;

import com.codeagentx.controlplane.domain.RunRecord;
import com.codeagentx.controlplane.workspace.LocalGitPatchBranchPreparer;
import com.codeagentx.controlplane.workspace.PatchBranchPreparationResult;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

class LocalGitPatchBranchPreparerTest {
    @TempDir
    Path tempDir;

    @Test
    void checksOutPatchBranchInExecutionWorkspace() throws Exception {
        assumeTrue(run(tempDir, "git", "--version").exitCode == 0);
        run(tempDir, "git", "init");
        run(tempDir, "git", "config", "user.email", "codeagentx@example.com");
        run(tempDir, "git", "config", "user.name", "CodeAgent-X Test");
        Files.write(tempDir.resolve("app.py"), "value = 1\n".getBytes(StandardCharsets.UTF_8));
        run(tempDir, "git", "add", "app.py");
        run(tempDir, "git", "commit", "-m", "initial");

        RunRecord run = new RunRecord("task-1");
        run.setExecutionWorkspaceRoot(tempDir.toString());

        PatchBranchPreparationResult result = new LocalGitPatchBranchPreparer("codeagentx/run-")
            .preparePatchBranch(run);

        assertThat(result.getBranchName()).isEqualTo("codeagentx/run-" + run.getRunId());
        assertThat(run(tempDir, "git", "branch", "--show-current").output)
            .isEqualTo("codeagentx/run-" + run.getRunId());
    }

    private CommandResult run(Path cwd, String... command) throws Exception {
        ProcessBuilder builder = new ProcessBuilder(command);
        builder.directory(cwd.toFile());
        builder.redirectErrorStream(true);
        Process process = builder.start();
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        process.getInputStream().transferTo(output);
        int exitCode = process.waitFor();
        return new CommandResult(exitCode, output.toString(StandardCharsets.UTF_8).trim());
    }

    private static class CommandResult {
        private final int exitCode;
        private final String output;

        private CommandResult(int exitCode, String output) {
            this.exitCode = exitCode;
            this.output = output;
        }
    }
}
