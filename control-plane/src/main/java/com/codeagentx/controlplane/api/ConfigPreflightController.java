package com.codeagentx.controlplane.api;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/config")
public class ConfigPreflightController {
    private final String publisherMode;
    private final String githubApiBaseUrl;
    private final String githubToken;
    private final String githubRepository;
    private final String githubBaseBranch;
    private final String githubHeadBranchPrefix;
    private final String githubRemoteName;
    private final String githubWebhookSecret;
    private final String runtimeBaseUrl;
    private final String workspaceRoot;
    private final boolean callbacksEnabled;

    public ConfigPreflightController(
        @Value("${codeagentx.publisher.mode:noop}") String publisherMode,
        @Value("${codeagentx.github.api-base-url:https://api.github.com}") String githubApiBaseUrl,
        @Value("${codeagentx.github.token:}") String githubToken,
        @Value("${codeagentx.github.repository:}") String githubRepository,
        @Value("${codeagentx.github.base-branch:main}") String githubBaseBranch,
        @Value("${codeagentx.github.head-branch-prefix:codeagentx/run-}") String githubHeadBranchPrefix,
        @Value("${codeagentx.github.remote-name:origin}") String githubRemoteName,
        @Value("${codeagentx.github.webhook-secret:}") String githubWebhookSecret,
        @Value("${codeagentx.runtime.base-url}") String runtimeBaseUrl,
        @Value("${codeagentx.workspace.root:../.codeagentx/control-plane/workspaces}") String workspaceRoot,
        @Value("${codeagentx.callbacks.enabled:false}") boolean callbacksEnabled
    ) {
        this.publisherMode = publisherMode;
        this.githubApiBaseUrl = githubApiBaseUrl;
        this.githubToken = githubToken;
        this.githubRepository = githubRepository;
        this.githubBaseBranch = githubBaseBranch;
        this.githubHeadBranchPrefix = githubHeadBranchPrefix;
        this.githubRemoteName = githubRemoteName;
        this.githubWebhookSecret = githubWebhookSecret;
        this.runtimeBaseUrl = runtimeBaseUrl;
        this.workspaceRoot = workspaceRoot;
        this.callbacksEnabled = callbacksEnabled;
    }

    @GetMapping("/preflight")
    public Map<String, Object> preflight() {
        List<String> missing = new ArrayList<String>();
        List<String> warnings = new ArrayList<String>();
        boolean githubPublisher = "github".equalsIgnoreCase(trim(publisherMode));
        if (githubPublisher) {
            require("codeagentx.github.token", githubToken, missing);
            require("codeagentx.github.base-branch", githubBaseBranch, missing);
            require("codeagentx.github.remote-name", githubRemoteName, missing);
            if (!hasText(githubRepository)) {
                warnings.add("codeagentx.github.repository is not configured; each task must provide repositoryFullName");
            }
        }

        Map<String, Object> github = new LinkedHashMap<String, Object>();
        github.put("apiBaseUrl", githubApiBaseUrl);
        github.put("tokenConfigured", hasText(githubToken));
        github.put("repositoryConfigured", hasText(githubRepository));
        github.put("baseBranch", githubBaseBranch);
        github.put("headBranchPrefix", githubHeadBranchPrefix);
        github.put("remoteName", githubRemoteName);
        github.put("webhookSignatureRequired", hasText(githubWebhookSecret));

        Map<String, Object> callbacks = new LinkedHashMap<String, Object>();
        callbacks.put("enabled", callbacksEnabled);

        Map<String, Object> response = new LinkedHashMap<String, Object>();
        response.put("status", missing.isEmpty() ? "ready" : "needs_configuration");
        response.put("publisherMode", publisherMode);
        response.put("runtimeBaseUrl", runtimeBaseUrl);
        response.put("workspaceRoot", workspaceRoot);
        response.put("github", github);
        response.put("callbacks", callbacks);
        response.put("missing", missing);
        response.put("warnings", warnings);
        return response;
    }

    private void require(String name, String value, List<String> missing) {
        if (!hasText(value)) {
            missing.add(name);
        }
    }

    private boolean hasText(String value) {
        return value != null && !value.trim().isEmpty();
    }

    private String trim(String value) {
        return value == null ? "" : value.trim();
    }
}
