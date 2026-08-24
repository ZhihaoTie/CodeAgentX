package com.codeagentx.controlplane.domain;

import java.time.Instant;
import java.util.UUID;

import javax.persistence.Column;
import javax.persistence.Entity;
import javax.persistence.EnumType;
import javax.persistence.Enumerated;
import javax.persistence.Id;
import javax.persistence.Lob;
import javax.persistence.Table;

@Entity
@Table(name = "run_reviews")
public class ReviewRecord {
    @Id
    @Column(length = 64)
    private String reviewId;

    @Column(name = "run_id", nullable = false, length = 64)
    private String runId;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 32)
    private ReviewDecision decision;

    @Lob
    private String comment;

    @Column(nullable = false)
    private Instant createdAt;

    protected ReviewRecord() {
    }

    public ReviewRecord(String runId, ReviewDecision decision, String comment) {
        this.reviewId = UUID.randomUUID().toString();
        this.runId = runId;
        this.decision = decision;
        this.comment = comment;
        this.createdAt = Instant.now();
    }

    public String getReviewId() {
        return reviewId;
    }

    public String getRunId() {
        return runId;
    }

    public ReviewDecision getDecision() {
        return decision;
    }

    public String getComment() {
        return comment;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }
}
