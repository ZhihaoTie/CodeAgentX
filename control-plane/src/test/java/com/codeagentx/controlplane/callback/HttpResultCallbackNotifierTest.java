package com.codeagentx.controlplane.callback;

import com.codeagentx.controlplane.domain.RunRecord;
import com.codeagentx.controlplane.domain.RunStatus;
import com.codeagentx.controlplane.domain.TaskRecord;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestTemplate;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.header;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.jsonPath;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

class HttpResultCallbackNotifierTest {
    @Test
    void postsRunUpdateToTaskCallbackUrl() {
        RestTemplate restTemplate = new RestTemplate();
        MockRestServiceServer server = MockRestServiceServer.bindTo(restTemplate).build();
        HttpResultCallbackNotifier notifier = new HttpResultCallbackNotifier(restTemplate);
        TaskRecord task = new TaskRecord(
            "generic_rest",
            "Fix parser",
            "Parser should ignore blank lines.",
            "delivery-1",
            "https://github.com/acme/repo.git",
            "acme/repo",
            "main",
            null,
            "pytest -q",
            "ticket-42",
            "https://example.com/callbacks/42"
        );
        RunRecord run = new RunRecord(task.getTaskId());
        run.setStatus(RunStatus.SUCCEEDED);
        run.setRuntimeRunId("runtime-1");
        run.setPullRequestUrl("https://github.com/acme/repo/pull/7");

        server.expect(requestTo("https://example.com/callbacks/42"))
            .andExpect(header("X-CodeAgentX-Run-Id", run.getRunId()))
            .andExpect(header("X-CodeAgentX-External-Task-Id", "ticket-42"))
            .andExpect(jsonPath("$.runId").value(run.getRunId()))
            .andExpect(jsonPath("$.taskId").value(task.getTaskId()))
            .andExpect(jsonPath("$.externalTaskId").value("ticket-42"))
            .andExpect(jsonPath("$.source").value("generic_rest"))
            .andExpect(jsonPath("$.status").value("SUCCEEDED"))
            .andExpect(jsonPath("$.runtimeRunId").value("runtime-1"))
            .andExpect(jsonPath("$.pullRequestUrl").value("https://github.com/acme/repo/pull/7"))
            .andRespond(withSuccess("{}", MediaType.APPLICATION_JSON));

        notifier.notifyRunUpdated(run, task);

        server.verify();
    }

    @Test
    void skipsTasksWithoutCallbackUrl() {
        HttpResultCallbackNotifier notifier = new HttpResultCallbackNotifier(new RestTemplate());
        TaskRecord task = new TaskRecord("generic_rest", "Fix parser", "Details");
        RunRecord run = new RunRecord(task.getTaskId());

        notifier.notifyRunUpdated(run, task);

        assertThat(run.getRunId()).isNotBlank();
    }
}
