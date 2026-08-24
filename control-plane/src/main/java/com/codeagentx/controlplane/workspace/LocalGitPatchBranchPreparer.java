package com.codeagentx.controlplane.workspace;

import com.codeagentx.controlplane.domain.RunRecord;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

@Component
public class LocalGitPatchBranchPreparer implements PatchBranchPreparer {
    private final String headBranchPrefix;

    public LocalGitPatchBranchPreparer(
        @Value("${codeagentx.github.head-branch-prefix:codeagentx/run-}") String headBranchPrefix
    ) {
        this.headBranchPrefix = headBranchPrefix;
    }

    @Override
    public PatchBranchPreparationResult preparePatchBranch(RunRecord run) {
        String branchName = headBranchPrefix + run.getRunId();
        if (run.getExecutionWorkspaceRoot() == null) {
            return new PatchBranchPreparationResult(branchName, "no execution workspace root");
        }

        Path workspace = Paths.get(run.getExecutionWorkspaceRoot()).toAbsolutePath().normalize();
        if (!Files.isDirectory(workspace.resolve(".git"))) {
            return new PatchBranchPreparationResult(branchName, "execution workspace is not a git repository");
        }

        CommandResult result = runGit(workspace, "git", "checkout", "-B", branchName);
        if (result.exitCode != 0) {
            throw new IllegalStateException("failed to prepare patch branch: " + result.output);
        }
        return new PatchBranchPreparationResult(branchName, "checked out local patch branch");
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
