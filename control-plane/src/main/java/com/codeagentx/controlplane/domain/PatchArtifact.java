package com.codeagentx.controlplane.domain;

import javax.persistence.Column;
import javax.persistence.Embeddable;
import javax.persistence.Lob;

@Embeddable
public class PatchArtifact {
    @Lob
    private String diffText;

    @Lob
    private String testReport;

    @Lob
    private String changedFiles;

    @Column(length = 512)
    private String trajectoryReportPath;

    protected PatchArtifact() {
    }

    public PatchArtifact(
        String diffText,
        String testReport,
        String changedFiles,
        String trajectoryReportPath
    ) {
        this.diffText = diffText;
        this.testReport = testReport;
        this.changedFiles = changedFiles;
        this.trajectoryReportPath = trajectoryReportPath;
    }

    public String getDiffText() {
        return diffText;
    }

    public String getTestReport() {
        return testReport;
    }

    public String getChangedFiles() {
        return changedFiles;
    }

    public String getTrajectoryReportPath() {
        return trajectoryReportPath;
    }
}
