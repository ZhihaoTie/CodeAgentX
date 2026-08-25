package com.codeagentx.controlplane;

import com.codeagentx.controlplane.api.MetricsController;
import com.codeagentx.controlplane.domain.InMemoryRunRepository;
import com.codeagentx.controlplane.domain.RunRecord;
import com.codeagentx.controlplane.domain.RunStatus;
import com.codeagentx.controlplane.runtime.RuntimeClient;
import org.junit.jupiter.api.Test;
import org.springframework.web.client.RestTemplate;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class MetricsControllerTest {
    @Test
    @SuppressWarnings("unchecked")
    void returnsRunCountsAndOperationalConfigSnapshot() {
        InMemoryRunRepository repository = new InMemoryRunRepository();
        RunRecord running = new RunRecord("task-1");
        running.setStatus(RunStatus.RUNNING);
        repository.saveRun(running);

        RunRecord succeeded = new RunRecord("task-2");
        succeeded.setStatus(RunStatus.SUCCEEDED);
        repository.saveRun(succeeded);

        MetricsController controller = new MetricsController(
            repository,
            new RuntimeClient(new RestTemplate(), "http://runtime.test"),
            "noop",
            "D:\\workspaces",
            2,
            4,
            25
        );

        Map<String, Object> metrics = controller.metrics();
        Map<String, Object> runs = (Map<String, Object>) metrics.get("runs");
        Map<String, Integer> byStatus = (Map<String, Integer>) runs.get("byStatus");
        Map<String, Object> worker = (Map<String, Object>) metrics.get("worker");
        Map<String, Object> runtime = (Map<String, Object>) metrics.get("runtime");
        Map<String, Object> publisher = (Map<String, Object>) metrics.get("publisher");
        Map<String, Object> workspace = (Map<String, Object>) metrics.get("workspace");

        assertThat(metrics.get("generatedAt")).isInstanceOf(String.class);
        assertThat(runs).containsEntry("total", 2).containsEntry("active", 1).containsEntry("terminal", 1);
        assertThat(byStatus.get("RUNNING")).isEqualTo(1);
        assertThat(byStatus.get("SUCCEEDED")).isEqualTo(1);
        assertThat(byStatus.get("FAILED")).isEqualTo(0);
        assertThat(worker).containsEntry("corePoolSize", 2).containsEntry("maxPoolSize", 4).containsEntry("queueCapacity", 25);
        assertThat(runtime).containsEntry("baseUrl", "http://runtime.test");
        assertThat(publisher).containsEntry("mode", "noop");
        assertThat(workspace).containsEntry("root", "D:\\workspaces");
    }
}
