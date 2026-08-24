package com.codeagentx.controlplane.workspace;

import com.codeagentx.controlplane.domain.RunRecord;

public interface PatchBranchPreparer {
    PatchBranchPreparationResult preparePatchBranch(RunRecord run);
}
