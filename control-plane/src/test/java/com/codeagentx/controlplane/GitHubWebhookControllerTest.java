package com.codeagentx.controlplane;

import com.codeagentx.controlplane.api.GitHubWebhookController;
import com.codeagentx.controlplane.domain.RunRecord;
import com.codeagentx.controlplane.domain.RunStatus;
import com.codeagentx.controlplane.domain.TaskExecutionSpec;
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

import java.nio.charset.StandardCharsets;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(GitHubWebhookController.class)
@Import(GitHubWebhookSignatureVerifier.class)
@TestPropertySource(properties = {
    "codeagentx.github.webhook-secret=It's a Secret to Everybody",
    "codeagentx.github.default-verification-command=py -3.13 -B -m unittest discover -s tests -v"
})
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
    void acceptedIssueWebhookCreatesTaskWithRepositoryMetadataAndDefaultVerification() throws Exception {
        RunRecord run = new RunRecord("task-issue-1");
        run.setStatus(RunStatus.QUEUED);
        when(workflowService.createTaskAndRun(any(TaskExecutionSpec.class))).thenReturn(run);

        String body = "{"
            + "\"action\":\"opened\","
            + "\"issue\":{"
            + "\"title\":\"Fix normalize_title casing behavior\","
            + "\"body\":\"The function should return title case.\","
            + "\"html_url\":\"https://github.com/ZhihaoTie/CodeAgent/issues/1\""
            + "},"
            + "\"repository\":{"
            + "\"full_name\":\"ZhihaoTie/CodeAgent\","
            + "\"clone_url\":\"https://github.com/ZhihaoTie/CodeAgent.git\","
            + "\"default_branch\":\"main\""
            + "}"
            + "}";

        mockMvc.perform(post("/api/webhooks/github")
                .header("X-GitHub-Event", "issues")
                .header("X-GitHub-Delivery", "delivery-issue-1")
                .header("X-Hub-Signature-256", signatureFor(body))
                .contentType(MediaType.APPLICATION_JSON)
                .content(body))
            .andExpect(status().isAccepted())
            .andExpect(jsonPath("$.runId").value(run.getRunId()));

        org.mockito.ArgumentCaptor<TaskExecutionSpec> captor = org.mockito.ArgumentCaptor.forClass(TaskExecutionSpec.class);
        verify(workflowService).createTaskAndRun(captor.capture());
        TaskExecutionSpec spec = captor.getValue();
        assertThat(spec.getSource()).isEqualTo("github");
        assertThat(spec.getTitle()).isEqualTo("Fix normalize_title casing behavior");
        assertThat(spec.getIdempotencyKey()).isEqualTo("github:delivery-issue-1");
        assertThat(spec.getRepositoryUrl()).isEqualTo("https://github.com/ZhihaoTie/CodeAgent.git");
        assertThat(spec.getRepositoryFullName()).isEqualTo("ZhihaoTie/CodeAgent");
        assertThat(spec.getBaseBranch()).isEqualTo("main");
        assertThat(spec.getVerificationCommand()).isEqualTo("py -3.13 -B -m unittest discover -s tests -v");
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
    private String signatureFor(String body) throws Exception {
        Mac mac = Mac.getInstance("HmacSHA256");
        mac.init(new SecretKeySpec(
            "It's a Secret to Everybody".getBytes(StandardCharsets.UTF_8),
            "HmacSHA256"
        ));
        byte[] digest = mac.doFinal(body.getBytes(StandardCharsets.UTF_8));
        StringBuilder hex = new StringBuilder("sha256=");
        for (byte b : digest) {
            hex.append(String.format("%02x", b));
        }
        return hex.toString();
    }
}
