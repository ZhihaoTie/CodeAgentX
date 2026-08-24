package com.codeagentx.controlplane.domain;

import java.util.Collection;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;

public class InMemoryRunRepository implements RunRepositoryPort {
    private final ConcurrentMap<String, TaskRecord> tasks = new ConcurrentHashMap<String, TaskRecord>();
    private final ConcurrentMap<String, RunRecord> runs = new ConcurrentHashMap<String, RunRecord>();

    public TaskRecord saveTask(TaskRecord task) {
        tasks.put(task.getTaskId(), task);
        return task;
    }

    public RunRecord saveRun(RunRecord run) {
        runs.put(run.getRunId(), run);
        return run;
    }

    public TaskRecord getTask(String taskId) {
        return tasks.get(taskId);
    }

    public TaskRecord getTaskByIdempotencyKey(String idempotencyKey) {
        if (idempotencyKey == null || idempotencyKey.trim().isEmpty()) {
            return null;
        }
        for (TaskRecord task : tasks.values()) {
            if (idempotencyKey.trim().equals(task.getIdempotencyKey())) {
                return task;
            }
        }
        return null;
    }

    public RunRecord getRunByTaskId(String taskId) {
        for (RunRecord run : runs.values()) {
            if (taskId.equals(run.getTaskId())) {
                return run;
            }
        }
        return null;
    }

    public RunRecord getRunByPatchBranch(String patchBranch) {
        if (patchBranch == null || patchBranch.trim().isEmpty()) {
            return null;
        }
        for (RunRecord run : runs.values()) {
            if (patchBranch.trim().equals(run.getPatchBranch())) {
                return run;
            }
        }
        return null;
    }

    public RunRecord getRun(String runId) {
        return runs.get(runId);
    }

    public Collection<RunRecord> listRunsByStatus(RunStatus status) {
        List<RunRecord> result = new ArrayList<RunRecord>();
        for (RunRecord run : runs.values()) {
            if (status == run.getStatus()) {
                result.add(run);
            }
        }
        return result;
    }

    public Collection<RunRecord> listRuns() {
        return runs.values();
    }
}
