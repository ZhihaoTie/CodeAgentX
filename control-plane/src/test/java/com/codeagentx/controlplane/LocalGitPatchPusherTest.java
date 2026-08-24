package com.codeagentx.controlplane;

import com.codeagentx.controlplane.domain.RunRecord;
import com.codeagentx.controlplane.workspace.LocalGitPatchPusher;
import com.codeagentx.controlplane.workspace.PatchPushResult;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

class LocalGitPatchPusherTest {
    @TempDir
    Path tempDir;

    @Test
    void pushesPatchBranchToConfiguredRemote() throws Exception {
        assumeTrue(run(tempDir, "git", "--version").exitCode == 0);
        Path remote = tempDir.resolve("remote.git");
        Path workspace = tempDir.resolve("workspace");
        Files.createDirectories(workspace);
        run(tempDir, "git", "init", "--bare", remote.toString());
        run(workspace, "git", "init");
        run(workspace, "git", "config", "user.email", "codeagentx@example.com");
        run(workspace, "git", "config", "user.name", "CodeAgent-X Test");
        run(workspace, "git", "remote", "add", "origin", remote.toString());
        Files.write(workspace.resolve("app.py"), "value = 1\n".getBytes(StandardCharsets.UTF_8));
        run(workspace, "git", "add", "app.py");
        run(workspace, "git", "commit", "-m", "initial");

        RunRecord run = new RunRecord("task-1");
        run.setExecutionWorkspaceRoot(workspace.toString());
        run.setPatchBranch("codeagentx/run-" + run.getRunId());
        run(workspace, "git", "checkout", "-B", run.getPatchBranch());

        PatchPushResult result = new LocalGitPatchPusher("origin").pushPatch(run);

        assertThat(result.getPushedRef()).isEqualTo("origin/" + run.getPatchBranch());
        assertThat(run(remote, "git", "show-ref", "--verify", "refs/heads/" + run.getPatchBranch()).exitCode)
            .isEqualTo(0);
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
