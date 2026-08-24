package com.codeagentx.controlplane;

import com.codeagentx.controlplane.api.GitHubWebhookController;
import com.codeagentx.controlplane.github.GitHubWebhookSignatureVerifier;
import com.codeagentx.controlplane.workflow.RunWorkflowService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.Mockito.verifyNoInteractions;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(GitHubWebhookController.class)
@Import(GitHubWebhookSignatureVerifier.class)
@TestPropertySource(properties = "codeagentx.github.webhook-secret=It's a Secret to Everybody")
class GitHubWebhookControllerTest {
    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private RunWorkflowService workflowService;

    @Test
    void rejectsGitHubWebhookWhenSignatureIsInvalid() throws Exception {
        mockMvc.perform(post("/api/webhooks/github")
                .header("X-GitHub-Event", "issues")
                .header("X-GitHub-Delivery", "delivery-1")
                .header("X-Hub-Signature-256", "sha256=0000000000000000000000000000000000000000000000000000000000000000")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"action\":\"opened\"}"))
            .andExpect(status().isUnauthorized())
            .andExpect(jsonPath("$.status").value("invalid_signature"));

        verifyNoInteractions(workflowService);
    }

    @Test
    void acceptsGitHubWebhookWhenSignatureIsValid() throws Exception {
        String body = "{\"action\":\"unknown\"}";

        mockMvc.perform(post("/api/webhooks/github")
                .header("X-GitHub-Event", "issues")
                .header("X-GitHub-Delivery", "delivery-2")
                .header("X-Hub-Signature-256", "sha256=17251401885358e0f56c1588b594e89d2e974f671ced46292b7dbc39c4e15c51")
                .contentType(MediaType.APPLICATION_JSON)
                .content(body))
            .andExpect(status().isAccepted())
            .andExpect(jsonPath("$.status").value("ignored"));
    }
}
