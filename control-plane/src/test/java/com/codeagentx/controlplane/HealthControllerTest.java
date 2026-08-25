package com.codeagentx.controlplane;

import com.codeagentx.controlplane.api.HealthController;
import com.codeagentx.controlplane.github.GitHubWebhookSignatureVerifier;
import com.codeagentx.controlplane.runtime.RuntimeClient;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.datasource.SingleConnectionDataSource;
import org.springframework.web.client.RestTemplate;

import javax.sql.DataSource;
import java.sql.DriverManager;

import static org.assertj.core.api.Assertions.assertThat;

class HealthControllerTest {
    @Test
    void reportsOkWhenDatabaseAndRuntimeAreHealthy() throws Exception {
        DataSource dataSource = new SingleConnectionDataSource(
            DriverManager.getConnection("jdbc:h2:mem:health_ok;DB_CLOSE_DELAY=-1"),
            true
        );
        HealthController controller = new HealthController(
            dataSource,
            new StubRuntimeClient(true),
            new GitHubWebhookSignatureVerifier("secret"),
            "noop",
            "D:\\workspaces",
            true
        );

        assertThat(controller.health())
            .containsEntry("status", "ok")
            .containsEntry("database", "ok")
            .containsEntry("runtime", "ok")
            .containsEntry("publisherMode", "noop")
            .containsEntry("callbacksEnabled", true)
            .containsEntry("webhookSignatureRequired", true);
    }

    @Test
    void reportsDegradedWhenRuntimeIsUnavailable() throws Exception {
        DataSource dataSource = new SingleConnectionDataSource(
            DriverManager.getConnection("jdbc:h2:mem:health_degraded;DB_CLOSE_DELAY=-1"),
            true
        );
        HealthController controller = new HealthController(
            dataSource,
            new StubRuntimeClient(false),
            new GitHubWebhookSignatureVerifier(""),
            "github",
            "D:\\workspaces",
            false
        );

        assertThat(controller.health())
            .containsEntry("status", "degraded")
            .containsEntry("database", "ok")
            .containsEntry("runtime", "unavailable")
            .containsEntry("publisherMode", "github")
            .containsEntry("callbacksEnabled", false)
            .containsEntry("webhookSignatureRequired", false);
    }

    private static class StubRuntimeClient extends RuntimeClient {
        private final boolean healthy;

        private StubRuntimeClient(boolean healthy) {
            super(new RestTemplate(), "http://runtime.test");
            this.healthy = healthy;
        }

        @Override
        public boolean isHealthy() {
            return healthy;
        }
    }
}
