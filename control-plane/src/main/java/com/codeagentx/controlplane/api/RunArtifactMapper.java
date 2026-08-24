package com.codeagentx.controlplane.api;

import com.codeagentx.controlplane.domain.PatchArtifact;
import com.codeagentx.controlplane.domain.RunRecord;

import java.util.LinkedHashMap;
import java.util.Map;

public class RunArtifactMapper {
    public Map<String, Object> toArtifact(RunRecord run) {
        PatchArtifact artifact = run.getPatchArtifact();
        Map<String, Object> response = new LinkedHashMap<String, Object>();
        response.put("runId", run.getRunId());
        response.put("taskId", run.getTaskId());
        response.put("status", run.getStatus().name());
        response.put("patchBranch", run.getPatchBranch());
        response.put("patchCommitSha", run.getPatchCommitSha());
        response.put("patchPushedRef", run.getPatchPushedRef());
        response.put("pullRequestUrl", run.getPullRequestUrl());
        response.put("diffText", artifact.getDiffText());
        response.put("testReport", artifact.getTestReport());
        response.put("changedFiles", artifact.getChangedFiles());
        response.put("trajectoryReportPath", artifact.getTrajectoryReportPath());
        return response;
    }
}
