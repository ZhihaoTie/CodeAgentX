package com.codeagentx.controlplane.api;

import com.codeagentx.controlplane.domain.CallbackDeliveryRecord;
import com.codeagentx.controlplane.domain.RunRecord;
import com.codeagentx.controlplane.domain.TaskRecord;
import com.codeagentx.controlplane.domain.TaskExecutionSpec;
import com.codeagentx.controlplane.events.RunEventStreamHub;
import com.codeagentx.controlplane.workflow.InvalidRunStateException;
import com.codeagentx.controlplane.workflow.RunWorkflowService;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import javax.validation.Valid;
import java.io.IOException;
import java.util.Collection;
import java.util.Map;

@Validated
@RestController
@RequestMapping("/api")
public class RunController {
    private final RunWorkflowService workflowService;
    private final RunEventStreamHub eventStreamHub;
    private final RunTimelineMapper timelineMapper;
    private final RunArtifactMapper artifactMapper;
    private final GenericRestTaskAdapter genericRestTaskAdapter;

    public RunController(RunWorkflowService workflowService, RunEventStreamHub eventStreamHub, GenericRestTaskAdapter genericRestTaskAdapter) {
        this.workflowService = workflowService;
        this.eventStreamHub = eventStreamHub;
        this.timelineMapper = new RunTimelineMapper();
        this.artifactMapper = new RunArtifactMapper();
        this.genericRestTaskAdapter = genericRestTaskAdapter;
    }

    @ExceptionHandler(InvalidRunStateException.class)
    public ResponseEntity<Map<String, Object>> handleInvalidRunState(InvalidRunStateException exc) {
        return ResponseEntity.status(HttpStatus.CONFLICT).body(Map.<String, Object>of(
            "error",
            "invalid_run_state",
            "message",
            exc.getMessage()
        ));
    }
    @PostMapping("/tasks")
    public ResponseEntity<RunRecord> createTask(@Valid @RequestBody CreateTaskRequest request) {
        RunRecord run = workflowService.createTaskAndRun(new TaskExecutionSpec(
            request.getSource(),
            request.getTitle(),
            request.getBody(),
            request.getIdempotencyKey(),
            request.getRepositoryUrl(),
            request.getRepositoryFullName(),
            request.getBaseBranch(),
            request.getWorkspaceRoot(),
            request.getVerificationCommand()
        ));
        return ResponseEntity.status(HttpStatus.ACCEPTED).body(run);
    }

    @PostMapping("/adapters/generic/tasks")
    public ResponseEntity<RunRecord> createGenericTask(@Valid @RequestBody GenericTaskRequest request) {
        RunRecord run = workflowService.createTaskAndRun(genericRestTaskAdapter.toExecutionSpec(request));
        return ResponseEntity.status(HttpStatus.ACCEPTED).body(run);
    }

    @GetMapping("/runs/{runId}")
    public ResponseEntity<RunRecord> getRun(@PathVariable String runId) {
        RunRecord run = workflowService.getRun(runId);
        if (run == null) {
            return ResponseEntity.notFound().build();
        }
        return ResponseEntity.ok(run);
    }

    @GetMapping("/runs/{runId}/timeline")
    public ResponseEntity<Map<String, Object>> getRunTimeline(@PathVariable String runId) {
        RunRecord run = workflowService.getRun(runId);
        if (run == null) {
            return ResponseEntity.notFound().build();
        }
        return ResponseEntity.ok(timelineMapper.toTimeline(run));
    }

    @GetMapping("/runs/{runId}/artifact")
    public ResponseEntity<Map<String, Object>> getRunArtifact(@PathVariable String runId) {
        RunRecord run = workflowService.getRun(runId);
        if (run == null || run.getPatchArtifact() == null) {
            return ResponseEntity.notFound().build();
        }
        return ResponseEntity.ok(artifactMapper.toArtifact(run));
    }

    @PostMapping("/runs/{runId}/refresh")
    public ResponseEntity<RunRecord> refreshRun(@PathVariable String runId) {
        return ResponseEntity.ok(workflowService.refreshFromRuntime(runId));
    }

    @PostMapping("/runs/recover-queued")
    public ResponseEntity<Map<String, Object>> recoverQueuedRuns() {
        int recovered = workflowService.recoverQueuedRuns();
        return ResponseEntity.ok(Map.<String, Object>of("recovered", recovered));
    }

    @PostMapping("/runs/{runId}/review")
    public ResponseEntity<RunRecord> reviewRun(
        @PathVariable String runId,
        @Valid @RequestBody ReviewRunRequest request
    ) {
        RunRecord run = workflowService.reviewRun(
            runId,
            request.getDecision(),
            request.getComment()
        );
        return ResponseEntity.ok(run);
    }

    @PostMapping("/runs/{runId}/cancel")
    public ResponseEntity<RunRecord> cancelRun(
        @PathVariable String runId,
        @RequestBody(required = false) CancelRunRequest request
    ) {
        RunRecord run = workflowService.cancelRun(
            runId,
            request == null ? null : request.getReason()
        );
        return ResponseEntity.ok(run);
    }

    @GetMapping("/runs/{runId}/audit")
    public ResponseEntity<Map<String, Object>> getRunAudit(@PathVariable String runId) {
        RunRecord run = workflowService.getRun(runId);
        if (run == null) {
            return ResponseEntity.notFound().build();
        }
        TaskRecord task = workflowService.getTask(run.getTaskId());
        Collection<CallbackDeliveryRecord> deliveries = workflowService.listCallbackDeliveries(runId);
        Map<String, Object> response = new java.util.LinkedHashMap<String, Object>();
        response.put("runId", run.getRunId());
        response.put("taskId", run.getTaskId());
        response.put("status", run.getStatus().name());
        response.put("task", taskSummary(task));
        response.put("timeline", timelineMapper.toTimeline(run).get("items"));
        response.put("artifact", run.getPatchArtifact() == null ? null : artifactMapper.toArtifact(run));
        response.put("reviews", run.getReviews());
        response.put("callbackDeliveries", deliveries);
        response.put("summary", auditSummary(run, deliveries));
        return ResponseEntity.ok(response);
    }
    @GetMapping("/runs/{runId}/callback-deliveries")
    public ResponseEntity<Collection<CallbackDeliveryRecord>> getCallbackDeliveries(@PathVariable String runId) {
        RunRecord run = workflowService.getRun(runId);
        if (run == null) {
            return ResponseEntity.notFound().build();
        }
        return ResponseEntity.ok(workflowService.listCallbackDeliveries(runId));
    }
    @GetMapping("/runs/{runId}/events")
    public SseEmitter streamRunEvents(@PathVariable String runId) throws IOException {
        RunRecord run = workflowService.getRun(runId);
        if (run == null) {
            throw new IllegalArgumentException("run not found: " + runId);
        }
        return eventStreamHub.subscribe(run);
    }
    private Map<String, Object> taskSummary(TaskRecord task) {
        if (task == null) {
            return null;
        }
        Map<String, Object> response = new java.util.LinkedHashMap<String, Object>();
        response.put("taskId", task.getTaskId());
        response.put("source", task.getSource());
        response.put("title", task.getTitle());
        response.put("externalTaskId", task.getExternalTaskId());
        response.put("repositoryUrl", task.getRepositoryUrl());
        response.put("repositoryFullName", task.getRepositoryFullName());
        response.put("baseBranch", task.getBaseBranch());
        response.put("verificationCommand", task.getVerificationCommand());
        response.put("provider", task.getProvider());
        response.put("model", task.getModel());
        response.put("maxTurns", task.getMaxTurns());
        response.put("maxRunSeconds", task.getMaxRunSeconds());
        response.put("permissionMode", task.getPermissionMode());
        response.put("createdAt", task.getCreatedAt() == null ? null : task.getCreatedAt().toString());
        return response;
    }

    private Map<String, Object> auditSummary(RunRecord run, Collection<CallbackDeliveryRecord> deliveries) {
        Map<String, Object> response = new java.util.LinkedHashMap<String, Object>();
        response.put("hasPatch", run.getPatchArtifact() != null && run.getPatchArtifact().getDiffText() != null);
        response.put("hasVerification", run.getPatchArtifact() != null && run.getPatchArtifact().getTestReport() != null);
        response.put("hasReview", !run.getReviews().isEmpty());
        response.put("hasPr", run.getPullRequestUrl() != null);
        response.put("hasCi", run.getStatus().name().startsWith("CI_") || run.getFinalText() != null && run.getFinalText().contains("CI "));
        response.put("hasCallback", deliveries != null && !deliveries.isEmpty());
        return response;
    }
}
