package com.codeagentx.controlplane;

import com.codeagentx.controlplane.api.RunController;
import com.codeagentx.controlplane.events.RunEventStreamHub;
import com.codeagentx.controlplane.workflow.InvalidRunStateException;
import com.codeagentx.controlplane.workflow.RunWorkflowService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(RunController.class)
@Import(RunEventStreamHub.class)
class RunControllerTest {
    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private RunWorkflowService workflowService;

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