package com.codeagentx.controlplane.runtime;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

import java.util.Map;

@Component
public class RuntimeClient {
    private final RestTemplate restTemplate;
    private final String baseUrl;

    @Autowired
    public RuntimeClient(@Value("${codeagentx.runtime.base-url}") String baseUrl) {
        this(new RestTemplate(), baseUrl);
    }

    public RuntimeClient(RestTemplate restTemplate, String baseUrl) {
        this.restTemplate = restTemplate;
        this.baseUrl = trimTrailingSlash(baseUrl);
    }

    public RuntimeRunResponse submitRun(RuntimeRunRequest request) {
        return restTemplate.postForObject(
            baseUrl + "/internal/runs",
            request,
            RuntimeRunResponse.class
        );
    }

    public RuntimeRunResponse getRun(String runtimeRunId) {
        return restTemplate.getForObject(
            baseUrl + "/internal/runs/" + runtimeRunId,
            RuntimeRunResponse.class
        );
    }

    public boolean isHealthy() {
        try {
            Map<?, ?> response = restTemplate.getForObject(baseUrl + "/health", Map.class);
            return response != null;
        } catch (Exception e) {
            return false;
        }
    }

    public String getBaseUrl() {
        return baseUrl;
    }

    private static String trimTrailingSlash(String value) {
        if (value == null || value.endsWith("/") == false) {
            return value;
        }
        return value.substring(0, value.length() - 1);
    }
}
