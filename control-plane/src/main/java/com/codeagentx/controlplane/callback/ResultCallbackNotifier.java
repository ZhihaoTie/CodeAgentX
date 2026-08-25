package com.codeagentx.controlplane.callback;

import com.codeagentx.controlplane.domain.RunRecord;
import com.codeagentx.controlplane.domain.TaskRecord;

public interface ResultCallbackNotifier {
    void notifyRunUpdated(RunRecord run, TaskRecord task);
}
