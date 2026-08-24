package com.codeagentx.controlplane.publisher;

import com.codeagentx.controlplane.domain.RunRecord;
import com.codeagentx.controlplane.domain.TaskRecord;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

@Component
@ConditionalOnProperty(
    name = "codeagentx.publisher.mode",
    havingValue = "noop",
    matchIfMissing = true
)
public class NoopResultPublisher implements ResultPublisher {
    @Override
    public PublishResult publishPullRequest(RunRecord run, TaskRecord task) {
        return new PublishResult("noop://pull-requests/" + run.getRunId());
    }
}
