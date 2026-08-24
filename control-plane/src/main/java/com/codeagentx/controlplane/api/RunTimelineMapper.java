package com.codeagentx.controlplane.api;

import com.codeagentx.controlplane.domain.ReviewRecord;
import com.codeagentx.controlplane.domain.RunEventRecord;
import com.codeagentx.controlplane.domain.RunRecord;

import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public class RunTimelineMapper {
    public Map<String, Object> toTimeline(RunRecord run) {
        List<Map<String, Object>> items = new ArrayList<Map<String, Object>>();
        for (RunEventRecord event : run.getEvents()) {
            Map<String, Object> item = new LinkedHashMap<String, Object>();
            item.put("kind", "EVENT");
            item.put("id", event.getEventId());
            item.put("type", event.getEventType());
            item.put("createdAt", instant(event.getCreatedAt()));
            item.put("payload", event.getPayload());
            items.add(item);
        }
        for (ReviewRecord review : run.getReviews()) {
            Map<String, Object> item = new LinkedHashMap<String, Object>();
            item.put("kind", "REVIEW");
            item.put("id", review.getReviewId());
            item.put("type", review.getDecision().name());
            item.put("createdAt", instant(review.getCreatedAt()));
            item.put("comment", review.getComment());
            items.add(item);
        }
        items.sort(Comparator.comparing(item -> String.valueOf(item.get("createdAt"))));

        Map<String, Object> response = new LinkedHashMap<String, Object>();
        response.put("runId", run.getRunId());
        response.put("taskId", run.getTaskId());
        response.put("status", run.getStatus().name());
        response.put("items", items);
        return response;
    }

    private String instant(Instant instant) {
        return instant == null ? null : instant.toString();
    }
}
