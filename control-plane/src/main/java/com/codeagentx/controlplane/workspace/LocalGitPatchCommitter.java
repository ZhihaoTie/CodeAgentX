package com.codeagentx.controlplane.workspace;

import com.codeagentx.controlplane.domain.RunRecord;
import org.springframework.stereotype.Component;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

@Component
public class LocalGitPatchCommitter implements PatchCommitter {
    @Override
    public PatchCommitResult commitPatch(RunRecord run) {
        if (run.getExecutionWorkspaceRoot() == null) {
            return new PatchCommitResult(null, "no execution workspace root");
        }
        Path workspace = Paths.get(run.getExecutionWorkspaceRoot()).toAbsolutePath().normalize();
        if (!Files.isDirectory(workspace.resolve(".git"))) {
            return new PatchCommitResult(null, "execution workspace is not a git repository");
        }

        CommandResult status = runGit(workspace, "git", "status", "--porcelain");
        if (status.exitCode != 0) {
            throw new IllegalStateException("failed to inspect git status: " + status.output);
        }
        if (status.output.trim().isEmpty()) {
            CommandResult head = runGit(workspace, "git", "rev-parse", "HEAD");
            if (head.exitCode != 0) {
                throw new IllegalStateException("failed to resolve HEAD: " + head.output);
            }
            return new PatchCommitResult(head.output.trim(), "no workspace changes to commit");
        }

        CommandResult add = runGit(workspace, "git", "add", "-A");
        if (add.exitCode != 0) {
            throw new IllegalStateException("failed to stage patch: " + add.output);
        }

        CommandResult commit = runGit(
            workspace,
            "git",
            "commit",
            "-m",
            "CodeAgent-X run " + run.getRunId()
        );
        if (commit.exitCode != 0) {
            throw new IllegalStateException("failed to commit patch: " + commit.output);
        }

        CommandResult sha = runGit(workspace, "git", "rev-parse", "HEAD");
        if (sha.exitCode != 0) {
            throw new IllegalStateException("failed to resolve patch commit: " + sha.output);
        }
        return new PatchCommitResult(sha.output.trim(), "committed workspace changes");
    }

    private CommandResult runGit(Path cwd, String... command) {
        try {
            ProcessBuilder builder = new ProcessBuilder(command);
            builder.directory(cwd.toFile());
            builder.redirectErrorStream(true);
            Process process = builder.start();
            ByteArrayOutputStream output = new ByteArrayOutputStream();
            process.getInputStream().transferTo(output);
            int exitCode = process.waitFor();
            return new CommandResult(exitCode, output.toString(StandardCharsets.UTF_8).trim());
        } catch (IOException exc) {
            return new CommandResult(1, exc.getMessage());
        } catch (InterruptedException exc) {
            Thread.currentThread().interrupt();
            return new CommandResult(1, "interrupted");
        }
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
