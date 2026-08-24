package com.codeagentx.controlplane.api;

import com.codeagentx.controlplane.domain.RunRecord;
import com.codeagentx.controlplane.domain.RunRepositoryPort;
import com.codeagentx.controlplane.domain.RunStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.Instant;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api")
public class RunSummaryController {
    private static final int RECENT_RUN_LIMIT = 10;
    private final RunRepositoryPort repository;

    public RunSummaryController(RunRepositoryPort repository) {
        this.repository = repository;
    }

    @GetMapping("/runs/summary")
    public Map<String, Object> summary() {
        Collection<RunRecord> runs = repository.listRuns();
        Map<String, Integer> byStatus = emptyStatusCounts();
        for (RunRecord run : runs) {
            byStatus.put(run.getStatus().name(), byStatus.get(run.getStatus().name()) + 1);
        }

        List<RunRecord> sortedRuns = new ArrayList<RunRecord>(runs);
        sortedRuns.sort(Comparator.comparing(RunRecord::getUpdatedAt).reversed());

        List<Map<String, Object>> recentRuns = new ArrayList<Map<String, Object>>();
        for (RunRecord run : sortedRuns) {
            if (recentRuns.size() >= RECENT_RUN_LIMIT) {
                break;
            }
            recentRuns.add(toSummary(run));
        }

        Map<String, Object> response = new LinkedHashMap<String, Object>();
        response.put("totalRuns", runs.size());
        response.put("byStatus", byStatus);
        response.put("recentRuns", recentRuns);
        return response;
    }

    private Map<String, Integer> emptyStatusCounts() {
        Map<String, Integer> counts = new LinkedHashMap<String, Integer>();
        for (RunStatus status : RunStatus.values()) {
            counts.put(status.name(), 0);
        }
        return counts;
    }

    private Map<String, Object> toSummary(RunRecord run) {
        Map<String, Object> summary = new LinkedHashMap<String, Object>();
        summary.put("runId", run.getRunId());
        summary.put("taskId", run.getTaskId());
        summary.put("status", run.getStatus().name());
        summary.put("runtimeRunId", run.getRuntimeRunId());
        summary.put("patchBranch", run.getPatchBranch());
        summary.put("pullRequestUrl", run.getPullRequestUrl());
        summary.put("createdAt", instant(run.getCreatedAt()));
        summary.put("updatedAt", instant(run.getUpdatedAt()));
        return summary;
    }

    private String instant(Instant instant) {
        return instant == null ? null : instant.toString();
    }
}
