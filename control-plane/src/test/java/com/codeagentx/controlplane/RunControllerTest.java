package com.codeagentx.controlplane;

import com.codeagentx.controlplane.api.GenericRestTaskAdapter;
import com.codeagentx.controlplane.api.RunController;
import com.codeagentx.controlplane.domain.RunRecord;
import com.codeagentx.controlplane.domain.TaskExecutionSpec;
import com.codeagentx.controlplane.events.RunEventStreamHub;
import com.codeagentx.controlplane.workflow.InvalidRunStateException;
import com.codeagentx.controlplane.workflow.RunWorkflowService;
import org.junit.jupiter.api.Test;
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
                .content("{\"title\":\"Fix parser\",\"body\":\"Parser should ignore blank lines.\",\"idempotencyKey\":\"external-delivery-1\",\"externalTaskId\":\"ticket-42\",\"resultCallbackUrl\":\"https://example.com/callbacks/42\",\"repositoryUrl\":\"https://github.com/acme/repo.git\",\"repositoryFullName\":\"acme/repo\",\"baseBranch\":\"main\",\"verificationCommand\":\"pytest -q\",\"workspaceRoot\":\"D:/should/not/be/trusted\"}"))
            .andExpect(status().isAccepted());

        ArgumentCaptor<TaskExecutionSpec> specCaptor = ArgumentCaptor.forClass(TaskExecutionSpec.class);
        verify(workflowService).createTaskAndRun(specCaptor.capture());
        TaskExecutionSpec spec = specCaptor.getValue();
        assertThat(spec.getSource()).isEqualTo("generic_rest");
        assertThat(spec.getExternalTaskId()).isEqualTo("ticket-42");
        assertThat(spec.getResultCallbackUrl()).isEqualTo("https://example.com/callbacks/42");
        assertThat(spec.getRepositoryFullName()).isEqualTo("acme/repo");
        assertThat(spec.getWorkspaceRoot()).isNull();
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
