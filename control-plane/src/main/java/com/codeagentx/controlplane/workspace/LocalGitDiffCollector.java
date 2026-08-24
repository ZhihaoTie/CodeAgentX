package com.codeagentx.controlplane.workspace;

import com.codeagentx.controlplane.domain.PatchArtifact;
import com.codeagentx.controlplane.domain.RunRecord;
import org.springframework.stereotype.Component;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

@Component
public class LocalGitDiffCollector implements GitDiffCollector {
    @Override
    public PatchArtifact collect(RunRecord run, PatchArtifact runtimeArtifact) {
        if (run.getExecutionWorkspaceRoot() == null) {
            return runtimeArtifact;
        }
        Path workspace = Paths.get(run.getExecutionWorkspaceRoot()).toAbsolutePath().normalize();
        if (!Files.isDirectory(workspace.resolve(".git"))) {
            return runtimeArtifact;
        }

        String diff = runGit(workspace, "git", "diff", "--binary");
        String changedFiles = filterChangedFiles(runGit(workspace, "git", "status", "--porcelain"));

        if (isBlank(diff) && isBlank(changedFiles)) {
            return runtimeArtifact;
        }

        return new PatchArtifact(
            prefer(diff, runtimeArtifact == null ? null : runtimeArtifact.getDiffText()),
            runtimeArtifact == null ? null : runtimeArtifact.getTestReport(),
            prefer(changedFiles, runtimeArtifact == null ? null : runtimeArtifact.getChangedFiles()),
            runtimeArtifact == null ? null : runtimeArtifact.getTrajectoryReportPath()
        );
    }


    private String filterChangedFiles(String changedFiles) {
        if (isBlank(changedFiles)) {
            return changedFiles;
        }
        StringBuilder filtered = new StringBuilder();
        for (String line : changedFiles.split("\\R")) {
            String trimmed = line.trim();
            if (trimmed.endsWith(".codeagentx/") || trimmed.contains(" .codeagentx/")) {
                continue;
            }
            if (filtered.length() > 0) {
                filtered.append(System.lineSeparator());
            }
            filtered.append(line);
        }
        return filtered.length() == 0 ? null : filtered.toString();
    }
    private String runGit(Path cwd, String... command) {
        try {
            ProcessBuilder builder = new ProcessBuilder(command);
            builder.directory(cwd.toFile());
            builder.redirectErrorStream(true);
            Process process = builder.start();
            ByteArrayOutputStream output = new ByteArrayOutputStream();
            process.getInputStream().transferTo(output);
            int exitCode = process.waitFor();
            if (exitCode != 0) {
                return null;
            }
            return output.toString(StandardCharsets.UTF_8).trim();
        } catch (IOException exc) {
            return null;
        } catch (InterruptedException exc) {
            Thread.currentThread().interrupt();
            return null;
        }
    }

    private String prefer(String primary, String fallback) {
        return isBlank(primary) ? fallback : primary;
    }

    private boolean isBlank(String value) {
        return value == null || value.trim().isEmpty();
    }
}
