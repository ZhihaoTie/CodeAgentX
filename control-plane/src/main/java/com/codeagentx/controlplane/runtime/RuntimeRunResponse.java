package com.codeagentx.controlplane.runtime;

import com.codeagentx.controlplane.domain.PatchArtifact;
import com.fasterxml.jackson.annotation.JsonProperty;

public class RuntimeRunResponse {
    @JsonProperty("run_id")
    private String runId;
    private String status;
    @JsonProperty("final_text")
    private String finalText;
    private String error;
    @JsonProperty("patch_diff")
    private String patchDiff;
    @JsonProperty("test_report")
    private String testReport;
    @JsonProperty("changed_files")
    private String changedFiles;
    @JsonProperty("trajectory_report_path")
    private String trajectoryReportPath;

    public String getRunId() {
        return runId;
    }

    public void setRunId(String runId) {
        this.runId = runId;
    }

    public String getStatus() {
        return status;
    }

    public void setStatus(String status) {
        this.status = status;
    }

    public String getFinalText() {
        return finalText;
    }

    public void setFinalText(String finalText) {
        this.finalText = finalText;
    }

    public String getError() {
        return error;
    }

    public void setError(String error) {
        this.error = error;
    }

    public String getPatchDiff() {
        return patchDiff;
    }

    public void setPatchDiff(String patchDiff) {
        this.patchDiff = patchDiff;
    }

    public String getTestReport() {
        return testReport;
    }

    public void setTestReport(String testReport) {
        this.testReport = testReport;
    }

    public String getChangedFiles() {
        return changedFiles;
    }

    public void setChangedFiles(String changedFiles) {
        this.changedFiles = changedFiles;
    }

    public String getTrajectoryReportPath() {
        return trajectoryReportPath;
    }

    public void setTrajectoryReportPath(String trajectoryReportPath) {
        this.trajectoryReportPath = trajectoryReportPath;
    }

    public PatchArtifact toPatchArtifact() {
        if (isBlank(patchDiff) && isBlank(testReport) && isBlank(changedFiles) && isBlank(trajectoryReportPath)) {
            return null;
        }
        return new PatchArtifact(patchDiff, testReport, changedFiles, trajectoryReportPath);
    }

    private static boolean isBlank(String value) {
        return value == null || value.trim().isEmpty();
    }
}
