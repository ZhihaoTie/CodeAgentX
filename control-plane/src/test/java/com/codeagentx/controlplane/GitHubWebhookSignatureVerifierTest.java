package com.codeagentx.controlplane;

import com.codeagentx.controlplane.github.GitHubWebhookSignatureVerifier;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class GitHubWebhookSignatureVerifierTest {
    @Test
    void acceptsAllPayloadsWhenSecretIsNotConfigured() {
        GitHubWebhookSignatureVerifier verifier = new GitHubWebhookSignatureVerifier("");

        assertThat(verifier.isRequired()).isFalse();
        assertThat(verifier.isValid(null, "{\"ok\":true}")).isTrue();
    }

    @Test
    void validatesSha256SignatureWhenSecretIsConfigured() {
        GitHubWebhookSignatureVerifier verifier = new GitHubWebhookSignatureVerifier("It's a Secret to Everybody");
        String body = "Hello, World!";

        assertThat(verifier.isRequired()).isTrue();
        assertThat(verifier.isValid(
            "sha256=757107ea0eb2509fc211221cce984b8a37570b6d7586c22c46f4379c8b043e17",
            body
        )).isTrue();
        assertThat(verifier.isValid(
            "sha256=0000000000000000000000000000000000000000000000000000000000000000",
            body
        )).isFalse();
    }
}
