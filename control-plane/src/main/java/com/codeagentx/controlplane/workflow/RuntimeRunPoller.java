package com.codeagentx.controlplane.workflow;

import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
public class RuntimeRunPoller {
    private final RunWorkflowService workflowService;

    public RuntimeRunPoller(RunWorkflowService workflowService) {
        this.workflowService = workflowService;
    }

    @Scheduled(fixedDelayString = "${codeagentx.runtime.poll-delay-ms:5000}")
    public void pollRunningRuns() {
        workflowService.refreshRunningRuns();
        workflowService.failTimedOutRuns();
    }
}
