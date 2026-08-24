package com.codeagentx.controlplane.workspace;

import com.codeagentx.controlplane.domain.RunRecord;

public interface PatchCommitter {
    PatchCommitResult commitPatch(RunRecord run);
}
