package com.codeagentx.controlplane.publisher;

import com.codeagentx.controlplane.domain.RunRecord;
import com.codeagentx.controlplane.domain.TaskRecord;

public interface ResultPublisher {
    PublishResult publishPullRequest(RunRecord run, TaskRecord task);
}
