package com.codeagentx.controlplane.callback;

import com.codeagentx.controlplane.domain.CallbackDeliveryRecord;
import com.codeagentx.controlplane.domain.RunRecord;
import com.codeagentx.controlplane.domain.TaskRecord;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

@Component
@ConditionalOnProperty(name = "codeagentx.callbacks.enabled", havingValue = "false", matchIfMissing = true)
public class NoopResultCallbackNotifier implements ResultCallbackNotifier {
    @Override
    public CallbackDeliveryRecord notifyRunUpdated(RunRecord run, TaskRecord task) {
        // External callbacks are opt-in. The default notifier intentionally has no side effects.
        return null;
    }
}