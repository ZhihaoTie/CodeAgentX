package com.codeagentx.controlplane;

import com.codeagentx.controlplane.api.RunSummaryController;
import com.codeagentx.controlplane.domain.InMemoryRunRepository;
import com.codeagentx.controlplane.domain.RunRecord;
import com.codeagentx.controlplane.domain.RunStatus;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class RunSummaryControllerTest {
    @Test
    @SuppressWarnings("unchecked")
    void returnsStatusCountsAndRecentRuns() {
        InMemoryRunRepository repository = new InMemoryRunRepository();
        RunRecord queued = new RunRecord("task-1");
        queued.setStatus(RunStatus.QUEUED);
        repository.saveRun(queued);

        RunRecord succeeded = new RunRecord("task-2");
        succeeded.setStatus(RunStatus.SUCCEEDED);
        succeeded.setPatchBranch("codeagentx/run-2");
        succeeded.setPullRequestUrl("noop://pull-requests/2");
        repository.saveRun(succeeded);

        RunSummaryController controller = new RunSummaryController(repository);

        Map<String, Object> summary = controller.summary();
        Map<String, Integer> byStatus = (Map<String, Integer>) summary.get("byStatus");
        List<Map<String, Object>> recentRuns = (List<Map<String, Object>>) summary.get("recentRuns");

        assertThat(summary).containsEntry("totalRuns", 2);
        assertThat(byStatus.get("QUEUED")).isEqualTo(1);
        assertThat(byStatus.get("SUCCEEDED")).isEqualTo(1);
        assertThat(byStatus.get("FAILED")).isEqualTo(0);
        assertThat(recentRuns).hasSize(2);
        assertThat(recentRuns)
            .anySatisfy(run -> assertThat(run)
                .containsEntry("runId", succeeded.getRunId())
                .containsEntry("status", "SUCCEEDED")
                .containsEntry("patchBranch", "codeagentx/run-2")
                .containsEntry("pullRequestUrl", "noop://pull-requests/2"));
    }
}

