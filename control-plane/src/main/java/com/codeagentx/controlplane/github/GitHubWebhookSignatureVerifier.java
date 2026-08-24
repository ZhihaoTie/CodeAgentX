package com.codeagentx.controlplane.github;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

@Component
public class GitHubWebhookSignatureVerifier {
    private static final String SIGNATURE_PREFIX = "sha256=";
    private final String secret;

    public GitHubWebhookSignatureVerifier(
        @Value("${codeagentx.github.webhook-secret:}") String secret
    ) {
        this.secret = secret == null ? "" : secret.trim();
    }

    public boolean isRequired() {
        return !secret.isEmpty();
    }

    public boolean isValid(String signatureHeader, String rawBody) {
        if (!isRequired()) {
            return true;
        }
        if (signatureHeader == null || !signatureHeader.startsWith(SIGNATURE_PREFIX)) {
            return false;
        }
        String expected = SIGNATURE_PREFIX + hmacSha256Hex(rawBody == null ? "" : rawBody);
        return MessageDigest.isEqual(
            expected.getBytes(StandardCharsets.UTF_8),
            signatureHeader.getBytes(StandardCharsets.UTF_8)
        );
    }

    private String hmacSha256Hex(String rawBody) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
            byte[] digest = mac.doFinal(rawBody.getBytes(StandardCharsets.UTF_8));
            StringBuilder hex = new StringBuilder(digest.length * 2);
            for (byte b : digest) {
                hex.append(String.format("%02x", b));
            }
            return hex.toString();
        } catch (Exception e) {
            throw new IllegalStateException("Failed to verify GitHub webhook signature", e);
        }
    }
}
