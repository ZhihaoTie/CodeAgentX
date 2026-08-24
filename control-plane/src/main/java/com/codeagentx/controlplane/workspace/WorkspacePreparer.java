package com.codeagentx.controlplane.workspace;

import com.codeagentx.controlplane.domain.RunRecord;
import com.codeagentx.controlplane.domain.TaskRecord;

public interface WorkspacePreparer {
    WorkspacePreparationResult prepareWorkspace(TaskRecord task, RunRecord run);
}
