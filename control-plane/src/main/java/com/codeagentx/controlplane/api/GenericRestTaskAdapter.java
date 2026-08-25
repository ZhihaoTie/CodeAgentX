package com.codeagentx.controlplane.api;

import com.codeagentx.controlplane.domain.TaskExecutionSpec;
import org.springframework.stereotype.Component;

@Component
public class GenericRestTaskAdapter {
    public TaskExecutionSpec toExecutionSpec(GenericTaskRequest request) {
        return new TaskExecutionSpec(
            "generic_rest",
            request.getTitle(),
            request.getBody(),
            request.getIdempotencyKey(),
            request.getRepositoryUrl(),
            request.getRepositoryFullName(),
            request.getBaseBranch(),
            null,
            request.getVerificationCommand(),
            request.getExternalTaskId(),
            request.getResultCallbackUrl()
        );
    }
}
