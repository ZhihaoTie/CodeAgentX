package com.codeagentx.controlplane;

import com.codeagentx.controlplane.runtime.RuntimeRunRequest;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class RuntimeRunRequestJsonTest {
    @Test
    void serializesRuntimeConfigWithPythonApiFieldNames() throws Exception {
        RuntimeRunRequest request = new RuntimeRunRequest("Fix the failing test.");
        request.setPermissionMode("auto");
        request.setMaxTurns(12);
        request.setWorkspaceRoot("D:\\workspaces\\repo");
        request.setVerificationCommand("mvn test");

        String json = new ObjectMapper().writeValueAsString(request);

        assertThat(json).contains("\"permission_mode\":\"auto\"");
        assertThat(json).contains("\"max_turns\":12");
        assertThat(json).contains("\"workspace_root\":\"D:\\\\workspaces\\\\repo\"");
        assertThat(json).contains("\"verification_command\":\"mvn test\"");
    }
}
