package com.codeagentx.controlplane.workflow;

public class InvalidRunStateException extends RuntimeException {
    public InvalidRunStateException(String message) {
        super(message);
    }
}