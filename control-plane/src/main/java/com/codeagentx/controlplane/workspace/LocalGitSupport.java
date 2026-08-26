package com.codeagentx.controlplane.workspace;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermission;
import java.util.EnumSet;
import java.util.Map;
import java.util.Set;
import java.util.stream.Stream;

final class LocalGitSupport {
    private LocalGitSupport() {
    }

    static CommandResult trustWorkspace(Path workspace) {
        return runGit(workspace, "git", "config", "--global", "--add", "safe.directory", workspace.toString());
    }

    static void trustWorkspaceOrThrow(Path workspace, String action) {
        CommandResult trust = trustWorkspace(workspace);
        if (trust.exitCode != 0) {
            throw new IllegalStateException("failed to trust workspace before " + action + ": " + trust.output);
        }
    }

    static void makeWorkspaceWritable(Path workspace) {
        try {
            if (!Files.exists(workspace)) {
                return;
            }
            try (Stream<Path> paths = Files.walk(workspace)) {
                paths.forEach(LocalGitSupport::makePathWritable);
            }
        } catch (IOException exc) {
            throw new IllegalStateException("failed to make workspace writable: " + exc.getMessage(), exc);
        }
    }

    static CommandResult runGit(Path cwd, String... command) {
        return runGit(cwd, Map.of(), command);
    }

    static CommandResult runGit(Path cwd, Map<String, String> environment, String... command) {
        try {
            ProcessBuilder builder = new ProcessBuilder(command);
            builder.directory(cwd.toFile());
            builder.environment().putAll(environment);
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

    private static void makePathWritable(Path path) {
        try {
            Set<PosixFilePermission> permissions = Files.getPosixFilePermissions(path);
            permissions = permissions.isEmpty()
                ? EnumSet.noneOf(PosixFilePermission.class)
                : EnumSet.copyOf(permissions);
            permissions.add(PosixFilePermission.OWNER_READ);
            permissions.add(PosixFilePermission.OWNER_WRITE);
            permissions.add(PosixFilePermission.GROUP_READ);
            permissions.add(PosixFilePermission.GROUP_WRITE);
            permissions.add(PosixFilePermission.OTHERS_READ);
            permissions.add(PosixFilePermission.OTHERS_WRITE);
            if (Files.isDirectory(path)) {
                permissions.add(PosixFilePermission.OWNER_EXECUTE);
                permissions.add(PosixFilePermission.GROUP_EXECUTE);
                permissions.add(PosixFilePermission.OTHERS_EXECUTE);
            }
            Files.setPosixFilePermissions(path, permissions);
        } catch (UnsupportedOperationException ignored) {
            // Non-POSIX development filesystems, such as some Windows mounts, do not support POSIX permissions.
        } catch (IOException exc) {
            throw new IllegalStateException("failed to update permissions for " + path + ": " + exc.getMessage(), exc);
        }
    }

    static class CommandResult {
        final int exitCode;
        final String output;

        CommandResult(int exitCode, String output) {
            this.exitCode = exitCode;
            this.output = output;
        }
    }
}
