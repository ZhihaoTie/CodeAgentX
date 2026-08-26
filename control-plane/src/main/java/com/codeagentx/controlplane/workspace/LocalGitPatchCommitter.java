package com.codeagentx.controlplane.workspace;

import com.codeagentx.controlplane.domain.RunRecord;
import org.springframework.stereotype.Component;

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

        LocalGitSupport.trustWorkspaceOrThrow(workspace, "patch commit");
        configureCommitIdentity(workspace);

        LocalGitSupport.CommandResult status = LocalGitSupport.runGit(workspace, "git", "status", "--porcelain");
        if (status.exitCode != 0) {
            throw new IllegalStateException("failed to inspect git status: " + status.output);
        }
        if (status.output.trim().isEmpty()) {
            LocalGitSupport.CommandResult head = LocalGitSupport.runGit(workspace, "git", "rev-parse", "HEAD");
            if (head.exitCode != 0) {
                throw new IllegalStateException("failed to resolve HEAD: " + head.output);
            }
            return new PatchCommitResult(head.output.trim(), "no workspace changes to commit");
        }

        LocalGitSupport.CommandResult add = LocalGitSupport.runGit(workspace, "git", "add", "-A");
        if (add.exitCode != 0) {
            throw new IllegalStateException("failed to stage patch: " + add.output);
        }

        LocalGitSupport.CommandResult commit = LocalGitSupport.runGit(
            workspace,
            "git",
            "commit",
            "-m",
            "CodeAgent-X run " + run.getRunId()
        );
        if (commit.exitCode != 0) {
            throw new IllegalStateException("failed to commit patch: " + commit.output);
        }

        LocalGitSupport.CommandResult sha = LocalGitSupport.runGit(workspace, "git", "rev-parse", "HEAD");
        if (sha.exitCode != 0) {
            throw new IllegalStateException("failed to resolve patch commit: " + sha.output);
        }
        return new PatchCommitResult(sha.output.trim(), "committed workspace changes");
    }

    private void configureCommitIdentity(Path workspace) {
        LocalGitSupport.CommandResult email = LocalGitSupport.runGit(
            workspace,
            "git",
            "config",
            "user.email",
            "codeagentx@example.com"
        );
        if (email.exitCode != 0) {
            throw new IllegalStateException("failed to configure git user.email: " + email.output);
        }

        LocalGitSupport.CommandResult name = LocalGitSupport.runGit(
            workspace,
            "git",
            "config",
            "user.name",
            "CodeAgent-X"
        );
        if (name.exitCode != 0) {
            throw new IllegalStateException("failed to configure git user.name: " + name.output);
        }
    }
}
