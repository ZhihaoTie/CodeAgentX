package com.codeagentx.controlplane.workspace;

import com.codeagentx.controlplane.domain.RunRecord;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

@Component
public class LocalGitPatchPusher implements PatchPusher {
    private final String remoteName;

    public LocalGitPatchPusher(
        @Value("${codeagentx.github.remote-name:origin}") String remoteName
    ) {
        this.remoteName = remoteName;
    }

    @Override
    public PatchPushResult pushPatch(RunRecord run) {
        if (run.getExecutionWorkspaceRoot() == null) {
            return new PatchPushResult(null, "no execution workspace root");
        }
        if (run.getPatchBranch() == null) {
            return new PatchPushResult(null, "no patch branch");
        }
        Path workspace = Paths.get(run.getExecutionWorkspaceRoot()).toAbsolutePath().normalize();
        if (!Files.isDirectory(workspace.resolve(".git"))) {
            return new PatchPushResult(null, "execution workspace is not a git repository");
        }

        LocalGitSupport.trustWorkspaceOrThrow(workspace, "patch push");

        LocalGitSupport.CommandResult push = LocalGitSupport.runGit(
            workspace,
            "git",
            "push",
            remoteName,
            "HEAD:" + run.getPatchBranch()
        );
        if (push.exitCode != 0) {
            throw new IllegalStateException("failed to push patch branch: " + push.output);
        }
        return new PatchPushResult(remoteName + "/" + run.getPatchBranch(), "pushed patch branch");
    }
}
