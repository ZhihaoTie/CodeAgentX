package com.codeagentx.controlplane.domain;

import java.util.Collection;

public interface RunRepositoryPort {
    TaskRecord saveTask(TaskRecord task);

    RunRecord saveRun(RunRecord run);

    CallbackDeliveryRecord saveCallbackDelivery(CallbackDeliveryRecord delivery);

    TaskRecord getTask(String taskId);

    TaskRecord getTaskByIdempotencyKey(String idempotencyKey);

    RunRecord getRunByTaskId(String taskId);

    RunRecord getRunByPatchBranch(String patchBranch);

    RunRecord getRun(String runId);

    Collection<RunRecord> listRunsByStatus(RunStatus status);

    Collection<RunRecord> listRuns();

    Collection<CallbackDeliveryRecord> listCallbackDeliveries(String runId);
}
