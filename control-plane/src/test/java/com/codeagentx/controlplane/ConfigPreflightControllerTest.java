package com.codeagentx.controlplane;

import com.codeagentx.controlplane.api.ConfigPreflightController;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class ConfigPreflightControllerTest {
    @Test
    @SuppressWarnings("unchecked")
    void reportsMissingGitHubConfigurationWhenPublisherModeIsGitHub() {
        ConfigPreflightController controller = new ConfigPreflightController(
            "github",
            "https://api.github.com",
            "",
            "",
            "main",
            "codeagentx/run-",
            "origin",
            "secret",
            "http://127.0.0.1:8765",
            "D:\\workspaces"
        );

        Map<String, Object> response = controller.preflight();
        Map<String, Object> github = (Map<String, Object>) response.get("github");
        List<String> missing = (List<String>) response.get("missing");
        List<String> warnings = (List<String>) response.get("warnings");

        assertThat(response).containsEntry("status", "needs_configuration");
        assertThat(github)
            .containsEntry("tokenConfigured", false)
            .containsEntry("repositoryConfigured", false)
            .containsEntry("webhookSignatureRequired", true);
        assertThat(missing).contains("codeagentx.github.token");
        assertThat(warnings)
            .contains("codeagentx.github.repository is not configured; each task must provide repositoryFullName");
    }

    @Test
    @SuppressWarnings("unchecked")
    void reportsReadyForNoopPublisherWithoutGitHubSecrets() {
        ConfigPreflightController controller = new ConfigPreflightController(
            "noop",
            "https://api.github.com",
            "",
            "",
            "main",
            "codeagentx/run-",
            "origin",
            "",
            "http://127.0.0.1:8765",
            "D:\\workspaces"
        );

        Map<String, Object> response = controller.preflight();
        Map<String, Object> github = (Map<String, Object>) response.get("github");
        List<String> missing = (List<String>) response.get("missing");
        List<String> warnings = (List<String>) response.get("warnings");

        assertThat(response).containsEntry("status", "ready");
        assertThat(github)
            .containsEntry("tokenConfigured", false)
            .containsEntry("webhookSignatureRequired", false);
        assertThat(missing).isEmpty();
        assertThat(warnings).isEmpty();
    }

    @Test
    @SuppressWarnings("unchecked")
    void reportsReadyWithWarningWhenGitHubRepositoryWillComeFromTaskMetadata() {
        ConfigPreflightController controller = new ConfigPreflightController(
            "github",
            "https://api.github.com",
            "configured-token",
            "",
            "main",
            "codeagentx/run-",
            "origin",
            "",
            "http://127.0.0.1:8765",
            "D:\\workspaces"
        );

        Map<String, Object> response = controller.preflight();
        List<String> missing = (List<String>) response.get("missing");
        List<String> warnings = (List<String>) response.get("warnings");

        assertThat(response).containsEntry("status", "ready");
        assertThat(missing).isEmpty();
        assertThat(warnings)
            .contains("codeagentx.github.repository is not configured; each task must provide repositoryFullName");
    }
}
