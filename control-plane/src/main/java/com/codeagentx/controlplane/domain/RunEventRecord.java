package com.codeagentx.controlplane.domain;

import java.time.Instant;
import java.util.Collections;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;

import javax.persistence.CollectionTable;
import javax.persistence.Column;
import javax.persistence.ElementCollection;
import javax.persistence.Entity;
import javax.persistence.FetchType;
import javax.persistence.Id;
import javax.persistence.JoinColumn;
import javax.persistence.MapKeyColumn;
import javax.persistence.Table;

@Entity
@Table(name = "run_events")
public class RunEventRecord {
    @Id
    @Column(length = 64)
    private String eventId;

    @Column(name = "run_id", nullable = false, length = 64)
    private String runId;

    @Column(nullable = false, length = 64)
    private String eventType;

    @ElementCollection(fetch = FetchType.EAGER)
    @CollectionTable(
        name = "run_event_payloads",
        joinColumns = @JoinColumn(name = "event_id")
    )
    @MapKeyColumn(name = "payload_key")
    @Column(name = "payload_value")
    private Map<String, String> payload;

    @Column(nullable = false)
    private Instant createdAt;

    protected RunEventRecord() {
    }

    public RunEventRecord(String runId, String eventType, Map<String, Object> payload) {
        this.eventId = UUID.randomUUID().toString();
        this.runId = runId;
        this.eventType = eventType;
        this.payload = stringifyPayload(payload);
        this.createdAt = Instant.now();
    }

    public String getEventId() {
        return eventId;
    }

    public String getRunId() {
        return runId;
    }

    public String getEventType() {
        return eventType;
    }

    public Map<String, String> getPayload() {
        return Collections.unmodifiableMap(payload);
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    private static Map<String, String> stringifyPayload(Map<String, Object> payload) {
        Map<String, String> result = new LinkedHashMap<String, String>();
        for (Map.Entry<String, Object> entry : new HashMap<String, Object>(payload).entrySet()) {
            result.put(entry.getKey(), String.valueOf(entry.getValue()));
        }
        return result;
    }
}
