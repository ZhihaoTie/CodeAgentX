package com.codeagentx.controlplane.api;

import com.codeagentx.controlplane.domain.RunRecord;
import com.codeagentx.controlplane.domain.TaskExecutionSpec;
import com.codeagentx.controlplane.events.RunEventStreamHub;
import com.codeagentx.controlplane.workflow.RunWorkflowService;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import javax.validation.Valid;
import java.io.IOException;
import java.util.Map;

@Validated
@RestController
@RequestMapping("/api")
public class RunController {
    private final RunWorkflowService workflowService;
    private final RunEventStreamHub eventStreamHub;
    private final RunTimelineMapper timelineMapper;
    private final RunArtifactMapper artifactMapper;

    public RunController(RunWorkflowService workflowService, RunEventStreamHub eventStreamHub) {
        this.workflowService = workflowService;
        this.eventStreamHub = eventStreamHub;
        this.timelineMapper = new RunTimelineMapper();
        this.artifactMapper = new RunArtifactMapper();
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

    @GetMapping("/runs/{runId}/events")
    public SseEmitter streamRunEvents(@PathVariable String runId) throws IOException {
        RunRecord run = workflowService.getRun(runId);
        if (run == null) {
            throw new IllegalArgumentException("run not found: " + runId);
        }
        return eventStreamHub.subscribe(run);
    }
}
