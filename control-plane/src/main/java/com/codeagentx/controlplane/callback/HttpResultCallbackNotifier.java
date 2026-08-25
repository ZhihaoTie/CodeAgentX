package com.codeagentx.controlplane.callback;

import com.codeagentx.controlplane.domain.CallbackDeliveryRecord;
import com.codeagentx.controlplane.domain.RunRecord;
import com.codeagentx.controlplane.domain.TaskRecord;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Component;
import org.springframework.web.client.HttpStatusCodeException;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;

@Component
@ConditionalOnProperty(name = "codeagentx.callbacks.enabled", havingValue = "true")
public class HttpResultCallbackNotifier implements ResultCallbackNotifier {
    private static final int DEFAULT_MAX_ATTEMPTS = 3;
    private static final long DEFAULT_BACKOFF_MS = 100L;

    private final RestTemplate restTemplate;
    private final int maxAttempts;
    private final long backoffMs;

    public HttpResultCallbackNotifier() {
        this(new RestTemplate());
    }

    public HttpResultCallbackNotifier(RestTemplate restTemplate) {
        this(restTemplate, DEFAULT_MAX_ATTEMPTS, DEFAULT_BACKOFF_MS);
    }

    public HttpResultCallbackNotifier(RestTemplate restTemplate, int maxAttempts, long backoffMs) {
        this.restTemplate = restTemplate;
        this.maxAttempts = Math.max(1, maxAttempts);
        this.backoffMs = Math.max(0L, backoffMs);
    }

    @Override
    public CallbackDeliveryRecord notifyRunUpdated(RunRecord run, TaskRecord task) {
        if (task == null || task.getResultCallbackUrl() == null) {
            return null;
        }
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.add("X-CodeAgentX-Run-Id", run.getRunId());
        if (task.getExternalTaskId() != null) {
            headers.add("X-CodeAgentX-External-Task-Id", task.getExternalTaskId());
        }

        Integer responseCode = null;
        String lastError = null;
        for (int attempt = 1; attempt <= maxAttempts; attempt++) {
            try {
                ResponseEntity<Void> response = restTemplate.postForEntity(
                    task.getResultCallbackUrl(),
                    new HttpEntity<Map<String, Object>>(payload(run, task), headers),
                    Void.class
                );
                HttpStatus statusCode = response.getStatusCode();
                responseCode = statusCode.value();
                if (statusCode.is2xxSuccessful()) {
                    return delivery(run, task, "DELIVERED", attempt, responseCode, null, Instant.now());
                }
                lastError = "HTTP " + responseCode;
            } catch (HttpStatusCodeException exc) {
                responseCode = exc.getRawStatusCode();
                lastError = exc.getMessage();
            } catch (RestClientException exc) {
                lastError = exc.getMessage();
            }
            if (attempt < maxAttempts) {
                sleepBeforeRetry();
            }
        }
        return delivery(run, task, "FAILED", maxAttempts, responseCode, lastError, null);
    }

    Map<String, Object> payload(RunRecord run, TaskRecord task) {
        Map<String, Object> body = new LinkedHashMap<String, Object>();
        body.put("taskId", task.getTaskId());
        body.put("runId", run.getRunId());
        body.put("externalTaskId", task.getExternalTaskId());
        body.put("source", task.getSource());
        body.put("status", run.getStatus().name());
        body.put("runtimeRunId", run.getRuntimeRunId());
        body.put("patchBranch", run.getPatchBranch());
        body.put("pullRequestUrl", run.getPullRequestUrl());
        body.put("failureReason", run.getFailureReason());
        body.put("updatedAt", run.getUpdatedAt() == null ? null : run.getUpdatedAt().toString());
        return body;
    }

    private CallbackDeliveryRecord delivery(
        RunRecord run,
        TaskRecord task,
        String status,
        int attempt,
        Integer responseCode,
        String lastError,
        Instant deliveredAt
    ) {
        return new CallbackDeliveryRecord(
            task.getTaskId(),
            run.getRunId(),
            task.getExternalTaskId(),
            task.getResultCallbackUrl(),
            run.getStatus().name(),
            status,
            attempt,
            responseCode,
            lastError,
            deliveredAt
        );
    }

    private void sleepBeforeRetry() {
        if (backoffMs <= 0L) {
            return;
        }
        try {
            Thread.sleep(backoffMs);
        } catch (InterruptedException exc) {
            Thread.currentThread().interrupt();
        }
    }
}