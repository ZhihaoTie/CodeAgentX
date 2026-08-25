package com.codeagentx.controlplane.callback;

import com.codeagentx.controlplane.domain.RunRecord;
import com.codeagentx.controlplane.domain.TaskRecord;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.stereotype.Component;

@Component
@ConditionalOnMissingBean(ResultCallbackNotifier.class)
public class NoopResultCallbackNotifier implements ResultCallbackNotifier {
    @Override
    public void notifyRunUpdated(RunRecord run, TaskRecord task) {
        // External callbacks are opt-in. The default notifier intentionally has no side effects.
    }
}
