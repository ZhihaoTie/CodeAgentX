package com.codeagentx.controlplane.api;

import com.codeagentx.controlplane.domain.RunRecord;
import com.codeagentx.controlplane.domain.RunRepositoryPort;
import com.codeagentx.controlplane.domain.RunStatus;
import com.codeagentx.controlplane.runtime.RuntimeClient;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.Instant;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.Map;

@RestController
@RequestMapping("/api")
public class MetricsController {
    private final RunRepositoryPort repository;
    private final RuntimeClient runtimeClient;
    private final String publisherMode;
    private final String workspaceRoot;
    private final int workerCorePoolSize;
    private final int workerMaxPoolSize;
    private final int workerQueueCapacity;

    public MetricsController(
        RunRepositoryPort repository,
        RuntimeClient runtimeClient,
        @Value("${codeagentx.publisher.mode:noop}") String publisherMode,
        @Value("${codeagentx.workspace.root:../.codeagentx/control-plane/workspaces}") String workspaceRoot,
        @Value("${codeagentx.worker.core-pool-size:2}") int workerCorePoolSize,
        @Value("${codeagentx.worker.max-pool-size:2}") int workerMaxPoolSize,
        @Value("${codeagentx.worker.queue-capacity:100}") int workerQueueCapacity
    ) {
        this.repository = repository;
        this.runtimeClient = runtimeClient;
        this.publisherMode = publisherMode;
        this.workspaceRoot = workspaceRoot;
        this.workerCorePoolSize = workerCorePoolSize;
        this.workerMaxPoolSize = workerMaxPoolSize;
        this.workerQueueCapacity = workerQueueCapacity;
    }

    @GetMapping("/metrics")
    public Map<String, Object> metrics() {
        Collection<RunRecord> runs = repository.listRuns();
        Map<String, Integer> byStatus = emptyStatusCounts();
        int activeRuns = 0;
        int terminalRuns = 0;
        for (RunRecord run : runs) {
            RunStatus status = run.getStatus();
            byStatus.put(status.name(), byStatus.get(status.name()) + 1);
            if (isTerminal(status)) {
                terminalRuns++;
            } else {
                activeRuns++;
            }
        }

        Map<String, Object> response = new LinkedHashMap<String, Object>();
        response.put("generatedAt", Instant.now().toString());
        response.put("runs", runMetrics(runs.size(), activeRuns, terminalRuns, byStatus));
        response.put("worker", workerMetrics());
        response.put("runtime", runtimeMetrics());
        response.put("publisher", publisherMetrics());
        response.put("workspace", workspaceMetrics());
        return response;
    }

    private Map<String, Object> runMetrics(int totalRuns, int activeRuns, int terminalRuns, Map<String, Integer> byStatus) {
        Map<String, Object> runs = new LinkedHashMap<String, Object>();
        runs.put("total", totalRuns);
        runs.put("active", activeRuns);
        runs.put("terminal", terminalRuns);
        runs.put("byStatus", byStatus);
        return runs;
    }

    private Map<String, Object> workerMetrics() {
        Map<String, Object> worker = new LinkedHashMap<String, Object>();
        worker.put("corePoolSize", workerCorePoolSize);
        worker.put("maxPoolSize", workerMaxPoolSize);
        worker.put("queueCapacity", workerQueueCapacity);
        return worker;
    }

    private Map<String, Object> runtimeMetrics() {
        Map<String, Object> runtime = new LinkedHashMap<String, Object>();
        runtime.put("baseUrl", runtimeClient.getBaseUrl());
        return runtime;
    }

    private Map<String, Object> publisherMetrics() {
        Map<String, Object> publisher = new LinkedHashMap<String, Object>();
        publisher.put("mode", publisherMode);
        return publisher;
    }

    private Map<String, Object> workspaceMetrics() {
        Map<String, Object> workspace = new LinkedHashMap<String, Object>();
        workspace.put("root", workspaceRoot);
        return workspace;
    }

    private Map<String, Integer> emptyStatusCounts() {
        Map<String, Integer> counts = new LinkedHashMap<String, Integer>();
        for (RunStatus status : RunStatus.values()) {
            counts.put(status.name(), 0);
        }
        return counts;
    }

    private boolean isTerminal(RunStatus status) {
        return status == RunStatus.SUCCEEDED
            || status == RunStatus.FAILED
            || status == RunStatus.CANCELLED;
    }
}
