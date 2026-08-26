package com.codeagentx.controlplane.workspace;

import com.codeagentx.controlplane.domain.RunRecord;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.attribute.PosixFilePermission;
import java.util.EnumSet;
import java.util.Map;
import java.util.Set;

@Component
public class LocalGitPatchPusher implements PatchPusher {
    private final String remoteName;
    private final String token;

    public LocalGitPatchPusher(
        @Value("${codeagentx.github.remote-name:origin}") String remoteName,
        @Value("${codeagentx.github.token:}") String token
    ) {
        this.remoteName = remoteName;
        this.token = token == null ? "" : token.trim();
    }

    public LocalGitPatchPusher(String remoteName) {
        this(remoteName, "");
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

        LocalGitSupport.CommandResult push = push(workspace, run.getPatchBranch());
        if (push.exitCode != 0) {
            throw new IllegalStateException("failed to push patch branch: " + push.output);
        }
        return new PatchPushResult(remoteName + "/" + run.getPatchBranch(), "pushed patch branch");
    }

    private LocalGitSupport.CommandResult push(Path workspace, String patchBranch) {
        if (token.isBlank()) {
            return LocalGitSupport.runGit(workspace, "git", "push", remoteName, "HEAD:" + patchBranch);
        }

        Path askPass = null;
        try {
            askPass = Files.createTempFile("codeagentx-git-askpass-", ".sh");
            Files.writeString(
                askPass,
                "#!/bin/sh\n"
                    + "case \"$1\" in\n"
                    + "  *Username*) printf '%s\\n' 'x-access-token' ;;\n"
                    + "  *Password*) printf '%s\\n' \"$CODEAGENTX_GIT_TOKEN\" ;;\n"
                    + "  *) printf '%s\\n' '' ;;\n"
                    + "esac\n"
            );
            makeExecutable(askPass);
            return LocalGitSupport.runGit(
                workspace,
                Map.of(
                    "GIT_ASKPASS", askPass.toString(),
                    "GIT_TERMINAL_PROMPT", "0",
                    "CODEAGENTX_GIT_TOKEN", token
                ),
                "git",
                "push",
                remoteName,
                "HEAD:" + patchBranch
            );
        } catch (IOException exc) {
            return new LocalGitSupport.CommandResult(1, "failed to prepare git credentials helper: " + exc.getMessage());
        } finally {
            if (askPass != null) {
                try {
                    Files.deleteIfExists(askPass);
                } catch (IOException ignored) {
                    // Best-effort cleanup for a short-lived helper script that does not contain the token.
                }
            }
        }
    }

    private void makeExecutable(Path path) throws IOException {
        try {
            Set<PosixFilePermission> permissions = EnumSet.of(
                PosixFilePermission.OWNER_READ,
                PosixFilePermission.OWNER_WRITE,
                PosixFilePermission.OWNER_EXECUTE
            );
            Files.setPosixFilePermissions(path, permissions);
        } catch (UnsupportedOperationException ignored) {
            path.toFile().setExecutable(true, true);
        }
    }
}
