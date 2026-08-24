package com.codeagentx.controlplane;

import com.codeagentx.controlplane.domain.PatchArtifact;
import com.codeagentx.controlplane.domain.RunRecord;
import com.codeagentx.controlplane.workspace.LocalGitDiffCollector;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

class LocalGitDiffCollectorTest {
    @TempDir
    Path tempDir;

    @Test
    void collectsDiffAndChangedFilesFromGitWorkspace() throws Exception {
        assumeTrue(run(tempDir, "git", "--version") == 0);
        run(tempDir, "git", "init");
        run(tempDir, "git", "config", "user.email", "codeagentx@example.com");
        run(tempDir, "git", "config", "user.name", "CodeAgent-X Test");
        Files.write(tempDir.resolve("app.py"), "value = 1\n".getBytes(StandardCharsets.UTF_8));
        run(tempDir, "git", "add", "app.py");
        run(tempDir, "git", "commit", "-m", "initial");
        Files.write(tempDir.resolve("app.py"), "value = 2\n".getBytes(StandardCharsets.UTF_8));
        Files.createDirectories(tempDir.resolve(".codeagentx/trajectories"));
        Files.write(tempDir.resolve(".codeagentx/trajectories/run.json"), "{}\n".getBytes(StandardCharsets.UTF_8));

        RunRecord run = new RunRecord("task-1");
        run.setExecutionWorkspaceRoot(tempDir.toString());

        PatchArtifact artifact = new LocalGitDiffCollector().collect(
            run,
            new PatchArtifact(null, "pytest passed", null, "reports/run.md")
        );

        assertThat(artifact.getDiffText()).contains("diff --git");
        assertThat(artifact.getDiffText()).contains("value = 2");
        assertThat(artifact.getChangedFiles()).contains("app.py");
        assertThat(artifact.getChangedFiles()).doesNotContain(".codeagentx");
        assertThat(artifact.getTestReport()).isEqualTo("pytest passed");
        assertThat(artifact.getTrajectoryReportPath()).isEqualTo("reports/run.md");
    }

    private int run(Path cwd, String... command) throws Exception {
        ProcessBuilder builder = new ProcessBuilder(command);
        builder.directory(cwd.toFile());
        builder.redirectErrorStream(true);
        Process process = builder.start();
        process.getInputStream().transferTo(OutputStreamDiscard.INSTANCE);
        return process.waitFor();
    }

    private static class OutputStreamDiscard extends java.io.OutputStream {
        static final OutputStreamDiscard INSTANCE = new OutputStreamDiscard();

        @Override
        public void write(int b) {
        }
    }
}
