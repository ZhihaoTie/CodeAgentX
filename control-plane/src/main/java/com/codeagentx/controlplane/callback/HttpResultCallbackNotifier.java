package com.codeagentx.controlplane.callback;

import com.codeagentx.controlplane.domain.RunRecord;
import com.codeagentx.controlplane.domain.TaskRecord;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

import java.util.LinkedHashMap;
import java.util.Map;

@Component
@ConditionalOnProperty(name = "codeagentx.callbacks.enabled", havingValue = "true")
public class HttpResultCallbackNotifier implements ResultCallbackNotifier {
    private final RestTemplate restTemplate;

    public HttpResultCallbackNotifier() {
        this(new RestTemplate());
    }

    public HttpResultCallbackNotifier(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    @Override
    public void notifyRunUpdated(RunRecord run, TaskRecord task) {
        if (task == null || task.getResultCallbackUrl() == null) {
            return;
        }
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.add("X-CodeAgentX-Run-Id", run.getRunId());
        if (task.getExternalTaskId() != null) {
            headers.add("X-CodeAgentX-External-Task-Id", task.getExternalTaskId());
        }
        restTemplate.postForEntity(
            task.getResultCallbackUrl(),
            new HttpEntity<Map<String, Object>>(payload(run, task), headers),
            Void.class
        );
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
}
