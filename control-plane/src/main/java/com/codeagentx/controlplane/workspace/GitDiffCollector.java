package com.codeagentx.controlplane.workspace;

import com.codeagentx.controlplane.domain.PatchArtifact;
import com.codeagentx.controlplane.domain.RunRecord;

public interface GitDiffCollector {
    PatchArtifact collect(RunRecord run, PatchArtifact runtimeArtifact);
}
