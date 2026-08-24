package com.codeagentx.controlplane.domain.jpa;

import com.codeagentx.controlplane.domain.RunRecord;
import com.codeagentx.controlplane.domain.RunRepositoryPort;
import com.codeagentx.controlplane.domain.RunStatus;
import com.codeagentx.controlplane.domain.TaskRecord;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

import java.util.Collection;

@Repository
public class JpaRunRepository implements RunRepositoryPort {
    private final JpaTaskRepository taskRepository;
    private final JpaRunRecordRepository runRepository;

    public JpaRunRepository(
        JpaTaskRepository taskRepository,
        JpaRunRecordRepository runRepository
    ) {
        this.taskRepository = taskRepository;
        this.runRepository = runRepository;
    }

    @Override
    @Transactional
    public TaskRecord saveTask(TaskRecord task) {
        return taskRepository.save(task);
    }

    @Override
    @Transactional
    public RunRecord saveRun(RunRecord run) {
        return runRepository.save(run);
    }

    @Override
    @Transactional(readOnly = true)
    public TaskRecord getTask(String taskId) {
        return taskRepository.findById(taskId).orElse(null);
    }

    @Override
    @Transactional(readOnly = true)
    public TaskRecord getTaskByIdempotencyKey(String idempotencyKey) {
        if (idempotencyKey == null || idempotencyKey.trim().isEmpty()) {
            return null;
        }
        return taskRepository.findByIdempotencyKey(idempotencyKey.trim()).orElse(null);
    }

    @Override
    @Transactional(readOnly = true)
    public RunRecord getRunByTaskId(String taskId) {
        return runRepository.findFirstByTaskId(taskId).orElse(null);
    }

    @Override
    @Transactional(readOnly = true)
    public RunRecord getRunByPatchBranch(String patchBranch) {
        if (patchBranch == null || patchBranch.trim().isEmpty()) {
            return null;
        }
        return runRepository.findFirstByPatchBranch(patchBranch.trim()).orElse(null);
    }

    @Override
    @Transactional(readOnly = true)
    public RunRecord getRun(String runId) {
        return runRepository.findById(runId).orElse(null);
    }

    @Override
    @Transactional(readOnly = true)
    public Collection<RunRecord> listRunsByStatus(RunStatus status) {
        return runRepository.findByStatus(status);
    }

    @Override
    @Transactional(readOnly = true)
    public Collection<RunRecord> listRuns() {
        return runRepository.findAll();
    }
}
