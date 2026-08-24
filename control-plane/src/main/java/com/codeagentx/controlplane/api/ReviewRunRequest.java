package com.codeagentx.controlplane.api;

import com.codeagentx.controlplane.domain.ReviewDecision;

import javax.validation.constraints.NotNull;

public class ReviewRunRequest {
    @NotNull
    private ReviewDecision decision;

    private String comment;

    public ReviewDecision getDecision() {
        return decision;
    }

    public void setDecision(ReviewDecision decision) {
        this.decision = decision;
    }

    public String getComment() {
        return comment;
    }

    public void setComment(String comment) {
        this.comment = comment;
    }
}
