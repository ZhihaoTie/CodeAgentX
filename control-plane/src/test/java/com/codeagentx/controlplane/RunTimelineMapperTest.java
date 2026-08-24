package com.codeagentx.controlplane;

import com.codeagentx.controlplane.api.RunTimelineMapper;
import com.codeagentx.controlplane.domain.ReviewDecision;
import com.codeagentx.controlplane.domain.ReviewRecord;
import com.codeagentx.controlplane.domain.RunRecord;
import com.codeagentx.controlplane.domain.RunStatus;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class RunTimelineMapperTest {
    @Test
    @SuppressWarnings("unchecked")
    void mapsEventsAndReviewsIntoTimelineItems() {
        RunRecord run = new RunRecord("task-1");
        run.setStatus(RunStatus.NEEDS_REVIEW);
        run.addReview(new ReviewRecord(run.getRunId(), ReviewDecision.REQUEST_CHANGES, "Add a test."));

        Map<String, Object> timeline = new RunTimelineMapper().toTimeline(run);
        List<Map<String, Object>> items = (List<Map<String, Object>>) timeline.get("items");

        assertThat(timeline)
            .containsEntry("runId", run.getRunId())
            .containsEntry("taskId", "task-1")
            .containsEntry("status", "NEEDS_REVIEW");
        assertThat(items)
            .extracting(item -> item.get("kind"))
            .contains("EVENT", "REVIEW");
        assertThat(items)
            .anySatisfy(item -> {
                assertThat(item).containsEntry("kind", "REVIEW");
                assertThat(item).containsEntry("type", "REQUEST_CHANGES");
                assertThat(item).containsEntry("comment", "Add a test.");
            });
    }
}
