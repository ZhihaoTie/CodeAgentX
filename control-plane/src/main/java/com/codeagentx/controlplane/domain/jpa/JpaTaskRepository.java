package com.codeagentx.controlplane.domain.jpa;

import com.codeagentx.controlplane.domain.TaskRecord;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface JpaTaskRepository extends JpaRepository<TaskRecord, String> {
    Optional<TaskRecord> findByIdempotencyKey(String idempotencyKey);
}
