package com.codeagentx.controlplane.workflow;

import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Component;

@Component
public class RunRecoveryService {
    private final RunWorkflowService workflowService;

    public RunRecoveryService(RunWorkflowService workflowService) {
        this.workflowService = workflowService;
    }

    @EventListener(ApplicationReadyEvent.class)
    public void recoverOnStartup() {
        workflowService.recoverQueuedRuns();
    }
}
