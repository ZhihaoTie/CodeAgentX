package com.codeagentx.controlplane.publisher;

import com.codeagentx.controlplane.domain.RunRecord;
import com.codeagentx.controlplane.domain.TaskRecord;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

import java.util.Map;

@Component
@ConditionalOnProperty(
    name = "codeagentx.publisher.mode",
    havingValue = "github"
)
public class GitHubResultPublisher implements ResultPublisher {
    private final RestTemplate restTemplate;
    private final String apiBaseUrl;
    private final String token;
    private final String repository;
    private final String baseBranch;
    private final String headBranchPrefix;

    @Autowired
    public GitHubResultPublisher(
        @Value("${codeagentx.github.api-base-url:https://api.github.com}") String apiBaseUrl,
        @Value("${codeagentx.github.token:}") String token,
        @Value("${codeagentx.github.repository:}") String repository,
        @Value("${codeagentx.github.base-branch:main}") String baseBranch,
        @Value("${codeagentx.github.head-branch-prefix:codeagentx/run-}") String headBranchPrefix
    ) {
        this(new RestTemplate(), apiBaseUrl, token, repository, baseBranch, headBranchPrefix);
    }

    public GitHubResultPublisher(
        RestTemplate restTemplate,
        String apiBaseUrl,
        String token,
        String repository,
        String baseBranch,
        String headBranchPrefix
    ) {
        this.restTemplate = restTemplate;
        this.apiBaseUrl = trimTrailingSlash(apiBaseUrl);
        this.token = token;
        this.repository = repository;
        this.baseBranch = baseBranch;
        this.headBranchPrefix = headBranchPrefix;
    }

    @Override
    public PublishResult publishPullRequest(RunRecord run, TaskRecord task) {
        requireConfigured("codeagentx.github.token", token);
        String targetRepository = chooseRepository(task);
        requireConfigured("GitHub repository", targetRepository);

        GitHubPullRequestRequest request = buildRequest(run, task);
        HttpHeaders headers = new HttpHeaders();
        headers.setBearerAuth(token);
        headers.setAccept(java.util.Collections.singletonList(MediaType.APPLICATION_JSON));
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.add("X-GitHub-Api-Version", "2022-11-28");

        @SuppressWarnings("unchecked")
        Map<String, Object> response = restTemplate.postForObject(
            apiBaseUrl + "/repos/" + targetRepository + "/pulls",
            new HttpEntity<GitHubPullRequestRequest>(request, headers),
            Map.class
        );
        if (response == null || response.get("html_url") == null) {
            throw new IllegalStateException("GitHub did not return pull request html_url");
        }
        return new PublishResult(String.valueOf(response.get("html_url")));
    }

    public GitHubPullRequestRequest buildRequest(RunRecord run) {
        return buildRequest(run, null);
    }

    public GitHubPullRequestRequest buildRequest(RunRecord run, TaskRecord task) {
        String title = "CodeAgent-X: run " + run.getRunId();
        String body = "Created after human AUTHORIZE_PR review.\n\nRun: " + run.getRunId();
        if (run.getFinalText() != null && !run.getFinalText().trim().isEmpty()) {
            body = body + "\n\nRuntime result:\n\n" + run.getFinalText();
        }
        if (run.getPatchArtifact() != null) {
            body = body + "\n\nPatch artifact:\n\n"
                + "- Changed files: " + nullToEmpty(run.getPatchArtifact().getChangedFiles()) + "\n"
                + "- Test report: " + nullToEmpty(run.getPatchArtifact().getTestReport()) + "\n"
                + "- Trajectory: " + nullToEmpty(run.getPatchArtifact().getTrajectoryReportPath());
        }
        if (run.getPatchCommitSha() != null && !run.getPatchCommitSha().trim().isEmpty()) {
            body = body + "\n\nPatch commit: " + run.getPatchCommitSha();
        }
        if (run.getPatchPushedRef() != null && !run.getPatchPushedRef().trim().isEmpty()) {
            body = body + "\n\nPatch pushed ref: " + run.getPatchPushedRef();
        }
        return new GitHubPullRequestRequest(
            title,
            run.getPatchBranch() == null ? headBranchPrefix + run.getRunId() : run.getPatchBranch(),
            chooseBaseBranch(task),
            body
        );
    }

    private String chooseRepository(TaskRecord task) {
        if (task != null && task.getRepositoryFullName() != null && !task.getRepositoryFullName().trim().isEmpty()) {
            return task.getRepositoryFullName();
        }
        return repository;
    }

    private String chooseBaseBranch(TaskRecord task) {
        if (task != null && task.getBaseBranch() != null && !task.getBaseBranch().trim().isEmpty()) {
            return task.getBaseBranch();
        }
        return baseBranch;
    }

    private static void requireConfigured(String name, String value) {
        if (value == null || value.trim().isEmpty()) {
            throw new IllegalStateException(name + " is required for GitHub publishing");
        }
    }

    private static String trimTrailingSlash(String value) {
        if (value == null || !value.endsWith("/")) {
            return value;
        }
        return value.substring(0, value.length() - 1);
    }

    private static String nullToEmpty(String value) {
        return value == null ? "" : value;
    }
}
