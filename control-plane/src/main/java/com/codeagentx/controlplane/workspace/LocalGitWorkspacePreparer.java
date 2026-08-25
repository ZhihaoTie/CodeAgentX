package com.codeagentx.controlplane.workspace;

import com.codeagentx.controlplane.domain.RunRecord;
import com.codeagentx.controlplane.domain.TaskRecord;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

@Component
public class LocalGitWorkspacePreparer implements WorkspacePreparer {
    private final Path workspacesRoot;

    public LocalGitWorkspacePreparer(
        @Value("${codeagentx.workspace.root:../.codeagentx/control-plane/workspaces}") String workspacesRoot
    ) {
        this.workspacesRoot = Paths.get(workspacesRoot).toAbsolutePath().normalize();
    }

    @Override
    public WorkspacePreparationResult prepareWorkspace(TaskRecord task, RunRecord run) {
        if (task.getWorkspaceRoot() != null) {
            Path explicitWorkspace = Paths.get(task.getWorkspaceRoot()).toAbsolutePath().normalize();
            if (!Files.exists(explicitWorkspace)) {
                throw new IllegalStateException("workspace root does not exist: " + explicitWorkspace);
            }
            return new WorkspacePreparationResult(
                explicitWorkspace.toString(),
                "using explicit workspace root"
            );
        }

        if (task.getRepositoryUrl() == null) {
            return new WorkspacePreparationResult(null, "no workspace metadata provided");
        }

        Path runWorkspace = workspacesRoot.resolve(run.getRunId()).normalize();
        ensureInsideRoot(runWorkspace);
        try {
            Files.createDirectories(workspacesRoot);
            if (!Files.exists(runWorkspace)) {
                runCommand(workspacesRoot, "git", "clone", task.getRepositoryUrl(), runWorkspace.toString());
            }
            LocalGitSupport.makeWorkspaceWritable(runWorkspace);
            LocalGitSupport.trustWorkspaceOrThrow(runWorkspace, "workspace preparation");
            if (task.getBaseBranch() != null) {
                runCommand(runWorkspace, "git", "checkout", task.getBaseBranch());
            }
            LocalGitSupport.makeWorkspaceWritable(runWorkspace);
            return new WorkspacePreparationResult(
                runWorkspace.toString(),
                "prepared git workspace"
            );
        } catch (IOException exc) {
            throw new IllegalStateException("failed to prepare workspace: " + exc.getMessage(), exc);
        } catch (InterruptedException exc) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("workspace preparation interrupted", exc);
        }
    }

    private void ensureInsideRoot(Path path) {
        if (!path.startsWith(workspacesRoot)) {
            throw new IllegalStateException("workspace path escapes configured root: " + path);
        }
    }

    private void runCommand(Path cwd, String... command) throws IOException, InterruptedException {
        ProcessBuilder builder = new ProcessBuilder(command);
        builder.directory(cwd.toFile());
        builder.redirectOutput(ProcessBuilder.Redirect.DISCARD);
        builder.redirectError(ProcessBuilder.Redirect.DISCARD);
        Process process = builder.start();
        int exitCode = process.waitFor();
        if (exitCode != 0) {
            throw new IllegalStateException(
                "command failed with exit code " + exitCode + ": " + String.join(" ", command)
            );
        }
    }
}
