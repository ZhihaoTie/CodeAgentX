package com.codeagentx.controlplane.domain.jpa;

import com.codeagentx.controlplane.domain.RunRecord;
import com.codeagentx.controlplane.domain.RunStatus;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface JpaRunRecordRepository extends JpaRepository<RunRecord, String> {
    Optional<RunRecord> findFirstByTaskId(String taskId);

    Optional<RunRecord> findFirstByPatchBranch(String patchBranch);

    List<RunRecord> findByStatus(RunStatus status);
}
