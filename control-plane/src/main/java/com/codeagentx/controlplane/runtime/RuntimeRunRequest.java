package com.codeagentx.controlplane.runtime;

import com.fasterxml.jackson.annotation.JsonProperty;

public class RuntimeRunRequest {
    private String task;
    private String provider;
    private String model;

    @JsonProperty("permission_mode")
    private String permissionMode;

    @JsonProperty("max_turns")
    private Integer maxTurns;

    @JsonProperty("max_run_seconds")
    private Double maxRunSeconds;

    @JsonProperty("verification_command")
    private String verificationCommand;

    @JsonProperty("workspace_root")
    private String workspaceRoot;

    public RuntimeRunRequest() {
    }

    public RuntimeRunRequest(String task) {
        this.task = task;
        this.permissionMode = "auto";
    }

    public String getTask() {
        return task;
    }

    public void setTask(String task) {
        this.task = task;
    }

    public String getProvider() {
        return provider;
    }

    public void setProvider(String provider) {
        this.provider = provider;
    }

    public String getModel() {
        return model;
    }

    public void setModel(String model) {
        this.model = model;
    }

    public String getPermissionMode() {
        return permissionMode;
    }

    public void setPermissionMode(String permissionMode) {
        this.permissionMode = permissionMode;
    }

    public Integer getMaxTurns() {
        return maxTurns;
    }

    public void setMaxTurns(Integer maxTurns) {
        this.maxTurns = maxTurns;
    }

    public Double getMaxRunSeconds() {
        return maxRunSeconds;
    }

    public void setMaxRunSeconds(Double maxRunSeconds) {
        this.maxRunSeconds = maxRunSeconds;
    }

    public String getVerificationCommand() {
        return verificationCommand;
    }

    public void setVerificationCommand(String verificationCommand) {
        this.verificationCommand = verificationCommand;
    }

    public String getWorkspaceRoot() {
        return workspaceRoot;
    }

    public void setWorkspaceRoot(String workspaceRoot) {
        this.workspaceRoot = workspaceRoot;
    }
}
