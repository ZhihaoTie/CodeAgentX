package com.codeagentx.controlplane;

import com.codeagentx.controlplane.domain.RunRecord;
import com.codeagentx.controlplane.workspace.LocalGitPatchCommitter;
import com.codeagentx.controlplane.workspace.PatchCommitResult;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

class LocalGitPatchCommitterTest {
    @TempDir
    Path tempDir;

    @Test
    void commitsWorkspaceChangesAndReturnsHeadSha() throws Exception {
        assumeTrue(run(tempDir, "git", "--version").exitCode == 0);
        run(tempDir, "git", "init");
        run(tempDir, "git", "config", "user.email", "codeagentx@example.com");
        run(tempDir, "git", "config", "user.name", "CodeAgent-X Test");
        Files.write(tempDir.resolve("app.py"), "value = 1\n".getBytes(StandardCharsets.UTF_8));
        run(tempDir, "git", "add", "app.py");
        run(tempDir, "git", "commit", "-m", "initial");
        Files.write(tempDir.resolve("app.py"), "value = 2\n".getBytes(StandardCharsets.UTF_8));

        RunRecord run = new RunRecord("task-1");
        run.setExecutionWorkspaceRoot(tempDir.toString());

        PatchCommitResult result = new LocalGitPatchCommitter().commitPatch(run);

        assertThat(result.getCommitSha()).hasSize(40);
        assertThat(run(tempDir, "git", "status", "--porcelain").output).isEmpty();
        assertThat(run(tempDir, "git", "log", "-1", "--pretty=%s").output)
            .isEqualTo("CodeAgent-X run " + run.getRunId());
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
