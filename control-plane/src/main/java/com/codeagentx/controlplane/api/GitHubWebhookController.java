package com.codeagentx.controlplane.api;

import com.codeagentx.controlplane.domain.RunRecord;
import com.codeagentx.controlplane.domain.TaskExecutionSpec;
import com.codeagentx.controlplane.github.GitHubIssueWebhook;
import com.codeagentx.controlplane.github.GitHubWebhookSignatureVerifier;
import com.codeagentx.controlplane.github.GitHubWorkflowRunWebhook;
import com.codeagentx.controlplane.workflow.RunWorkflowService;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Collections;
import java.util.Map;

@RestController
@RequestMapping("/api/webhooks")
public class GitHubWebhookController {
    private final RunWorkflowService workflowService;
    private final ObjectMapper objectMapper;
    private final GitHubWebhookSignatureVerifier signatureVerifier;

    public GitHubWebhookController(
        RunWorkflowService workflowService,
        ObjectMapper objectMapper,
        GitHubWebhookSignatureVerifier signatureVerifier
    ) {
        this.workflowService = workflowService;
        this.objectMapper = objectMapper;
        this.signatureVerifier = signatureVerifier;
    }

    @PostMapping("/github")
    public ResponseEntity<?> receiveGitHubWebhook(
        @RequestHeader(value = "X-GitHub-Event", required = false) String event,
        @RequestHeader(value = "X-GitHub-Delivery", required = false) String deliveryId,
        @RequestHeader(value = "X-Hub-Signature-256", required = false) String signature,
        @RequestBody String rawBody
    ) {
        if (!signatureVerifier.isValid(signature, rawBody)) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body(
                Collections.singletonMap("status", "invalid_signature")
            );
        }

        Map<String, Object> payload = parsePayload(rawBody);
        GitHubWorkflowRunWebhook workflowRunWebhook = GitHubWorkflowRunWebhook.from(event, payload);
        if (workflowRunWebhook.isSupported()) {
            RunRecord run = workflowService.recordCiStatus(
                workflowRunWebhook.getHeadBranch(),
                workflowRunWebhook.getStatus(),
                workflowRunWebhook.getConclusion(),
                workflowRunWebhook.getUrl()
            );
            if (run == null) {
                return ResponseEntity.status(HttpStatus.ACCEPTED).body(
                    Collections.singletonMap("status", "unmatched")
                );
            }
            return ResponseEntity.status(HttpStatus.ACCEPTED).body(run);
        }

        GitHubIssueWebhook issueWebhook = GitHubIssueWebhook.from(event, deliveryId, payload);
        if (!issueWebhook.isSupported()) {
            return ResponseEntity.status(HttpStatus.ACCEPTED).body(
                Collections.singletonMap("status", "ignored")
            );
        }

        RunRecord run = workflowService.createTaskAndRun(new TaskExecutionSpec(
            "github",
            issueWebhook.getTitle(),
            issueWebhook.getBody(),
            issueWebhook.getIdempotencyKey(),
            issueWebhook.getRepositoryUrl(),
            issueWebhook.getRepositoryFullName(),
            issueWebhook.getBaseBranch(),
            null,
            null
        ));
        return ResponseEntity.status(HttpStatus.ACCEPTED).body(run);
    }

    private Map<String, Object> parsePayload(String rawBody) {
        try {
            return objectMapper.readValue(rawBody, new TypeReference<Map<String, Object>>() {
            });
        } catch (Exception e) {
            return Collections.emptyMap();
        }
    }
}
