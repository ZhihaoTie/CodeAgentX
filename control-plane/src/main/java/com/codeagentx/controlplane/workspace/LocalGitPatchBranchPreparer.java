package com.codeagentx.controlplane.workspace;

import com.codeagentx.controlplane.domain.RunRecord;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

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

        LocalGitSupport.trustWorkspaceOrThrow(workspace, "patch branch preparation");
        LocalGitSupport.CommandResult result = LocalGitSupport.runGit(workspace, "git", "checkout", "-B", branchName);
        if (result.exitCode != 0) {
            throw new IllegalStateException("failed to prepare patch branch: " + result.output);
        }
        return new PatchBranchPreparationResult(branchName, "checked out local patch branch");
    }
}
