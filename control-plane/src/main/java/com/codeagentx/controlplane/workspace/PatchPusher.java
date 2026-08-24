package com.codeagentx.controlplane.workspace;

import com.codeagentx.controlplane.domain.RunRecord;

public interface PatchPusher {
    PatchPushResult pushPatch(RunRecord run);
}
