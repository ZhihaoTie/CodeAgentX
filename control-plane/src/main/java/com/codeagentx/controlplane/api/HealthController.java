package com.codeagentx.controlplane.api;

import com.codeagentx.controlplane.github.GitHubWebhookSignatureVerifier;
import com.codeagentx.controlplane.runtime.RuntimeClient;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import javax.sql.DataSource;
import java.sql.Connection;
import java.util.LinkedHashMap;
import java.util.Map;

@RestController
@RequestMapping("/api")
public class HealthController {
    private final DataSource dataSource;
    private final RuntimeClient runtimeClient;
    private final GitHubWebhookSignatureVerifier signatureVerifier;
    private final String publisherMode;
    private final String workspaceRoot;
    private final boolean callbacksEnabled;

    public HealthController(
        DataSource dataSource,
        RuntimeClient runtimeClient,
        GitHubWebhookSignatureVerifier signatureVerifier,
        @Value("${codeagentx.publisher.mode:noop}") String publisherMode,
        @Value("${codeagentx.workspace.root:../.codeagentx/control-plane/workspaces}") String workspaceRoot,
        @Value("${codeagentx.callbacks.enabled:false}") boolean callbacksEnabled
    ) {
        this.dataSource = dataSource;
        this.runtimeClient = runtimeClient;
        this.signatureVerifier = signatureVerifier;
        this.publisherMode = publisherMode;
        this.workspaceRoot = workspaceRoot;
        this.callbacksEnabled = callbacksEnabled;
    }

    @GetMapping("/health")
    public Map<String, Object> health() {
        boolean databaseHealthy = databaseHealthy();
        boolean runtimeHealthy = runtimeClient.isHealthy();

        Map<String, Object> response = new LinkedHashMap<String, Object>();
        response.put("status", databaseHealthy && runtimeHealthy ? "ok" : "degraded");
        response.put("database", databaseHealthy ? "ok" : "unavailable");
        response.put("runtime", runtimeHealthy ? "ok" : "unavailable");
        response.put("runtimeBaseUrl", runtimeClient.getBaseUrl());
        response.put("publisherMode", publisherMode);
        response.put("workspaceRoot", workspaceRoot);
        response.put("callbacksEnabled", callbacksEnabled);
        response.put("webhookSignatureRequired", signatureVerifier.isRequired());
        return response;
    }

    private boolean databaseHealthy() {
        try (Connection ignored = dataSource.getConnection()) {
            return true;
        } catch (Exception e) {
            return false;
        }
    }
}
