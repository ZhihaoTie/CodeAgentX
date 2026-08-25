package com.codeagentx.controlplane.domain;

import java.time.Instant;
import java.util.UUID;

import javax.persistence.Column;
import javax.persistence.Entity;
import javax.persistence.Id;
import javax.persistence.Lob;
import javax.persistence.Table;

@Entity
@Table(name = "callback_deliveries")
public class CallbackDeliveryRecord {
    @Id
    @Column(name = "delivery_id", length = 64)
    private String deliveryId;

    @Column(name = "task_id", length = 64)
    private String taskId;

    @Column(name = "run_id", nullable = false, length = 64)
    private String runId;

    @Column(name = "external_task_id", length = 256)
    private String externalTaskId;

    @Column(nullable = false, length = 1024)
    private String url;

    @Column(nullable = false, length = 64)
    private String event;

    @Column(nullable = false, length = 32)
    private String status;

    @Column(nullable = false)
    private int attempt;

    @Column(name = "response_code")
    private Integer responseCode;

    @Lob
    @Column(name = "last_error")
    private String lastError;

    @Column(name = "delivered_at")
    private Instant deliveredAt;

    @Column(nullable = false)
    private Instant createdAt;

    protected CallbackDeliveryRecord() {
    }

    public CallbackDeliveryRecord(
        String taskId,
        String runId,
        String externalTaskId,
        String url,
        String event,
        String status,
        int attempt,
        Integer responseCode,
        String lastError,
        Instant deliveredAt
    ) {
        this.deliveryId = UUID.randomUUID().toString();
        this.taskId = taskId;
        this.runId = runId;
        this.externalTaskId = blankToNull(externalTaskId);
        this.url = url;
        this.event = event;
        this.status = status;
        this.attempt = attempt;
        this.responseCode = responseCode;
        this.lastError = blankToNull(lastError);
        this.deliveredAt = deliveredAt;
        this.createdAt = Instant.now();
    }

    public static CallbackDeliveryRecord skipped(RunRecord run, TaskRecord task) {
        return null;
    }

    public String getDeliveryId() { return deliveryId; }
    public String getTaskId() { return taskId; }
    public String getRunId() { return runId; }
    public String getExternalTaskId() { return externalTaskId; }
    public String getUrl() { return url; }
    public String getEvent() { return event; }
    public String getStatus() { return status; }
    public int getAttempt() { return attempt; }
    public Integer getResponseCode() { return responseCode; }
    public String getLastError() { return lastError; }
    public Instant getDeliveredAt() { return deliveredAt; }
    public Instant getCreatedAt() { return createdAt; }

    private String blankToNull(String value) {
        if (value == null || value.trim().isEmpty()) {
            return null;
        }
        return value.trim();
    }
}