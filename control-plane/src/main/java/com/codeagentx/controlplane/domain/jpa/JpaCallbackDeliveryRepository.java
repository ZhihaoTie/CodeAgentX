package com.codeagentx.controlplane.domain.jpa;

import com.codeagentx.controlplane.domain.CallbackDeliveryRecord;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface JpaCallbackDeliveryRepository extends JpaRepository<CallbackDeliveryRecord, String> {
    List<CallbackDeliveryRecord> findByRunIdOrderByCreatedAtAsc(String runId);
}