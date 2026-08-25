package com.codeagentx.controlplane;

import com.codeagentx.controlplane.api.GenericRestTaskAdapter;
import com.codeagentx.controlplane.domain.CallbackDeliveryRecord;
import com.codeagentx.controlplane.api.RunController;
import com.codeagentx.controlplane.domain.RunRecord;
import com.codeagentx.controlplane.domain.TaskRecord;
import com.codeagentx.controlplane.domain.TaskExecutionSpec;
import com.codeagentx.controlplane.events.RunEventStreamHub;
import com.codeagentx.controlplane.workflow.InvalidRunStateException;
import com.codeagentx.controlplane.workflow.RunWorkflowService;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.Collections;
import java.util.List;
import org.mockito.ArgumentCaptor;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(RunController.class)
@Import({RunEventStreamHub.class, GenericRestTaskAdapter.class})
class RunControllerTest {
    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private RunWorkflowService workflowService;

    @Test
    void genericRestAdapterCreatesStandardTaskWithoutExternalWorkspaceControl() throws Exception {
        RunRecord accepted = new RunRecord("task-1");
        when(workflowService.createTaskAndRun(any(TaskExecutionSpec.class))).thenReturn(accepted);

        mockMvc.perform(post("/api/adapters/generic/tasks")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"title\":\"Fix parser\",\"body\":\"Parser should ignore blank lines.\",\"idempotencyKey\":\"external-delivery-1\",\"externalTaskId\":\"ticket-42\",\"resultCallbackUrl\":\"https://example.com/callbacks/42\",\"repositoryUrl\":\"https://github.com/acme/repo.git\",\"repositoryFullName\":\"acme/repo\",\"baseBranch\":\"main\",\"verificationCommand\":\"pytest -q\",\"workspaceRoot\":\"D:/should/not/be/trusted\",\"provider\":\"mock\",\"model\":\"mock-model\",\"maxTurns\":2,\"maxRunSeconds\":15.5,\"permissionMode\":\"auto\"}"))
            .andExpect(status().isAccepted());

        ArgumentCaptor<TaskExecutionSpec> specCaptor = ArgumentCaptor.forClass(TaskExecutionSpec.class);
        verify(workflowService).createTaskAndRun(specCaptor.capture());
        TaskExecutionSpec spec = specCaptor.getValue();
        assertThat(spec.getSource()).isEqualTo("generic_rest");
        assertThat(spec.getExternalTaskId()).isEqualTo("ticket-42");
        assertThat(spec.getResultCallbackUrl()).isEqualTo("https://example.com/callbacks/42");
        assertThat(spec.getRepositoryFullName()).isEqualTo("acme/repo");
        assertThat(spec.getWorkspaceRoot()).isNull();
        assertThat(spec.getProvider()).isEqualTo("mock");
        assertThat(spec.getModel()).isEqualTo("mock-model");
        assertThat(spec.getMaxTurns()).isEqualTo(2);
        assertThat(spec.getMaxRunSeconds()).isEqualTo(15.5);
        assertThat(spec.getPermissionMode()).isEqualTo("auto");
    }



    @Test
    void auditEndpointReturnsExecutionTrail() throws Exception {
        RunRecord run = new RunRecord("task-1");
        TaskRecord task = new TaskRecord(
            "generic_rest",
            "Fix parser",
            "Details",
            "delivery-1",
            null,
            "acme/repo",
            "main",
            null,
            "pytest -q",
            "ticket-42",
            "https://example.com/callbacks/42",
            "mock",
            "mock-model",
            1,
            15.0,
            "auto"
        );
        when(workflowService.getRun(run.getRunId())).thenReturn(run);
        when(workflowService.getTask(run.getTaskId())).thenReturn(task);
        when(workflowService.listCallbackDeliveries(run.getRunId())).thenReturn(Collections.singletonList(new CallbackDeliveryRecord(
            task.getTaskId(),
            run.getRunId(),
            "ticket-42",
            "https://example.com/callbacks/42",
            "QUEUED",
            "DELIVERED",
            1,
            200,
            null,
            Instant.parse("2026-08-25T10:00:00Z")
        )));

        mockMvc.perform(get("/api/runs/{runId}/audit", run.getRunId()))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.runId").value(run.getRunId()))
            .andExpect(jsonPath("$.task.source").value("generic_rest"))
            .andExpect(jsonPath("$.task.repositoryFullName").value("acme/repo"))
            .andExpect(jsonPath("$.task.provider").value("mock"))
            .andExpect(jsonPath("$.timeline[0].type").value("RUN_CREATED"))
            .andExpect(jsonPath("$.callbackDeliveries[0].status").value("DELIVERED"))
            .andExpect(jsonPath("$.summary.hasCallback").value(true));
    }
    @Test
    void callbackDeliveriesEndpointReturnsRunDeliveries() throws Exception {
        RunRecord run = new RunRecord("task-1");
        when(workflowService.getRun(run.getRunId())).thenReturn(run);
        when(workflowService.listCallbackDeliveries(run.getRunId())).thenReturn(Collections.singletonList(new CallbackDeliveryRecord(
            "task-1",
            run.getRunId(),
            "ticket-42",
            "https://example.com/callbacks/42",
            "NEEDS_REVIEW",
            "DELIVERED",
            2,
            200,
            null,
            Instant.parse("2026-08-25T10:00:00Z")
        )));

        mockMvc.perform(get("/api/runs/{runId}/callback-deliveries", run.getRunId()))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$[0].runId").value(run.getRunId()))
            .andExpect(jsonPath("$[0].externalTaskId").value("ticket-42"))
            .andExpect(jsonPath("$[0].event").value("NEEDS_REVIEW"))
            .andExpect(jsonPath("$[0].status").value("DELIVERED"))
            .andExpect(jsonPath("$[0].attempt").value(2))
            .andExpect(jsonPath("$[0].responseCode").value(200));
    }
    @Test
    void reviewRunReturnsConflictForInvalidRunState() throws Exception {
        when(workflowService.reviewRun(eq("run-1"), any(), any()))
            .thenThrow(new InvalidRunStateException(
                "Review decision AUTHORIZE_PR requires run status APPROVED but was NEEDS_REVIEW"
            ));

        mockMvc.perform(post("/api/runs/run-1/review")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"decision\":\"AUTHORIZE_PR\",\"comment\":\"Ship it.\"}"))
            .andExpect(status().isConflict())
            .andExpect(jsonPath("$.error").value("invalid_run_state"))
            .andExpect(jsonPath("$.message").value(
                "Review decision AUTHORIZE_PR requires run status APPROVED but was NEEDS_REVIEW"
            ));
    }
}
