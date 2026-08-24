package com.codeagentx.controlplane;

import com.codeagentx.controlplane.domain.RunRecord;
import com.codeagentx.controlplane.domain.PatchArtifact;
import com.codeagentx.controlplane.domain.TaskRecord;
import com.codeagentx.controlplane.publisher.GitHubPullRequestRequest;
import com.codeagentx.controlplane.publisher.GitHubResultPublisher;
import org.springframework.http.HttpEntity;
import org.springframework.web.client.RestTemplate;
import org.junit.jupiter.api.Test;

import java.util.HashMap;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class GitHubResultPublisherTest {
    @Test
    void buildsPullRequestRequestFromRun() {
        GitHubResultPublisher publisher = new GitHubResultPublisher(
            null,
            "https://api.github.com/",
            "token",
            "acme/repo",
            "main",
            "codeagentx/run-"
        );
        RunRecord run = new RunRecord("task-1");
        run.setFinalText("Patch summary.");
        run.setPatchArtifact(new PatchArtifact("diff", "pytest passed", "a.py", "reports/run.md"));
        run.setPatchBranch("codeagentx/custom-branch");
        run.setPatchCommitSha("0123456789012345678901234567890123456789");
        run.setPatchPushedRef("origin/codeagentx/custom-branch");
        TaskRecord task = new TaskRecord(
            "github",
            "Fix issue",
            "Details",
            null,
            "https://github.com/acme/repo.git",
            "acme/repo",
            "develop",
            null,
            null
        );

        GitHubPullRequestRequest request = publisher.buildRequest(run, task);

        assertThat(request.getTitle()).contains(run.getRunId());
        assertThat(request.getHead()).isEqualTo("codeagentx/custom-branch");
        assertThat(request.getBase()).isEqualTo("develop");
        assertThat(request.getBody()).contains("AUTHORIZE_PR");
        assertThat(request.getBody()).contains("Patch summary.");
        assertThat(request.getBody()).contains("a.py");
        assertThat(request.getBody()).contains("pytest passed");
        assertThat(request.getBody()).contains("0123456789012345678901234567890123456789");
        assertThat(request.getBody()).contains("origin/codeagentx/custom-branch");
    }

    @Test
    void publishesToTaskRepositoryWhenPresent() {
        CapturingRestTemplate restTemplate = new CapturingRestTemplate();
        GitHubResultPublisher publisher = new GitHubResultPublisher(
            restTemplate,
            "https://api.github.test/",
            "token",
            "fallback/repo",
            "main",
            "codeagentx/run-"
        );
        RunRecord run = new RunRecord("task-1");
        run.setPatchBranch("codeagentx/custom-branch");
        TaskRecord task = new TaskRecord(
            "github",
            "Fix issue",
            "Details",
            null,
            "https://github.com/acme/repo.git",
            "acme/repo",
            "main",
            null,
            null
        );

        publisher.publishPullRequest(run, task);

        assertThat(restTemplate.url).isEqualTo("https://api.github.test/repos/acme/repo/pulls");
    }

    private static class CapturingRestTemplate extends RestTemplate {
        private String url;

        @Override
        @SuppressWarnings("unchecked")
        public <T> T postForObject(String url, Object request, Class<T> responseType, Object... uriVariables) {
            this.url = url;
            assertThat(request).isInstanceOf(HttpEntity.class);
            Map<String, Object> response = new HashMap<String, Object>();
            response.put("html_url", "https://github.com/acme/repo/pull/1");
            return (T) response;
        }
    }
}
