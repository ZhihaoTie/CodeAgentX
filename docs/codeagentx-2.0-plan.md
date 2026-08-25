# CodeAgent-X 2.0 Project Plan

## Project Goal

CodeAgent-X 2.0 is a human-in-the-loop autonomous software engineering agent platform.

Its goal is not to build a chatbot or keep adding isolated agent features. The goal is to embed the existing CodeAgent-X Python runtime into a real software development workflow: issues enter from GitHub, the agent works inside a controlled sandbox, patches are reviewed interactively, pull requests are created only after authorization, and CI results are written back into the task state.

One-line positioning:

> CodeAgent-X combines a Python agent execution runtime with a Java/Spring Boot control plane to deliver reviewable, recoverable, auditable, CI-backed software engineering automation.

## Core Workflow

The target end-to-end workflow is:

```text
GitHub Issue
 -> Webhook
 -> Task / Run
 -> Python Agent Runtime
 -> Sandbox code modification
 -> Test verification
 -> Proposed Patch
 -> Interactive Review
 -> Revision / Approval
 -> Pull Request
 -> GitHub Actions CI
 -> Status writeback
```

Short form:

```text
Issue -> Agent Run -> Patch -> Review -> Revision -> PR -> CI
```

The important product decision is that review is not a final "approve patch" button. Review should be closer to Codex-style interactive engineering control:

```text
Agent proposes an action, command, patch, or PR
System shows risk, diff, tests, affected files, and trajectory evidence
Human approves, rejects, requests changes, or authorizes publication
Agent revises based on feedback
Runtime verifies the revised result
Platform writes the final result back to GitHub
```

## Architecture

CodeAgent-X 2.0 has two planes.

### Python Execution Plane

This is the existing CodeAgent-X runtime. It performs the real repository work.

Responsibilities:

```text
AgentLoop
ToolExecutor
Repository search
File read / edit / write
Shell execution
PatchTransaction
OutcomeVerifier
Failure Reflection
Retry Strategy
Context Ranking
TrajectoryStore
Benchmark Harness
```

It answers:

```text
How does the agent understand the task?
How does it inspect code?
How does it modify files?
How does it run tests?
How does it recover from failure?
How is the execution trace recorded?
```

### Java Business / Control Plane

This is the Spring Boot platform layer to be added around the runtime.

Responsibilities:

```text
Task / Run / Review / Approval
PostgreSQL persistence
Webhook handling
Async worker orchestration
SSE event streaming
GitHub integration
Idempotency
Timeout / retry
Crash recovery
Concurrency limits
```

It answers:

```text
How does a real business task enter the system?
How is a long-running agent task managed?
How does a user review and guide the agent?
How is remote GitHub state changed safely?
How does the system recover from failures?
```

## Five-Layer View

```text
                 CodeAgent-X 2.0

Business Layer
GitHub Issue -> PR -> CI

Backend Layer
Spring Boot / Task / Run / Review / DB / Workflow

Interaction Layer
Webhook / REST / SSE / Codex-like Review / Approval

Agent Layer
Python Runtime / Tool / Patch / Verify / Retry / Trajectory

Production Layer
Docker Sandbox / Idempotency / Recovery / Timeout / Deploy
```

## Target State Machine

Recommended platform-level task/run states:

```text
CREATED
QUEUED
RUNNING
PATCH_PROPOSED
NEEDS_REVIEW
CHANGES_REQUESTED
REVISING
APPROVED
PR_CREATING
PR_CREATED
CI_RUNNING
SUCCEEDED
FAILED
CANCELLED
```

Review actions:

```text
Approve
Request Changes
Reject
Authorize PR
```

`Request Changes` should feed a new instruction back into the Python runtime, for example:

```text
Keep the current approach, but do not change the public API.
Add a boundary test for the empty input case.
The patch is too large; only modify the service layer.
Rerun the full test command before proposing the patch again.
```

This turns review into an iterative engineering loop:

```text
Review Comment -> New Agent Instruction -> Patch Update -> Test -> Review
```

## Version Plan

## Planning Alignment Checkpoint

Current implementation is still aligned with the CodeAgent-X 2.0 plan.

The recent work did not shift the project toward "more agent tricks". It strengthened the platform/control-plane side required by the original goal:

```text
Health endpoint        -> production readiness / dependency diagnosis
Config preflight       -> safe readiness check before real GitHub publishing
Run summary endpoint   -> lightweight dashboard and operational visibility
Run cancellation       -> long-running task lifecycle control
Run timeline endpoint  -> auditability and review trace inspection
Run artifact endpoint  -> patch/test/trajectory evidence retrieval
Smoke profile          -> reproducible local vertical-slice demo
```

These map directly to the planned platform questions:

```text
How does the system expose operational state?      -> /api/health
How do we know GitHub publishing is configured?    -> /api/config/preflight
How can users see active and recent work?          -> /api/runs/summary
How are long-running tasks controlled?             -> /api/runs/{id}/cancel
How is the execution/review process audited?       -> /api/runs/{id}/timeline
How are patch and verification results inspected?  -> /api/runs/{id}/artifact
How can the vertical slice be demonstrated locally?-> smoke profile + smoke driver
```

The project is therefore still moving along the intended transformation:

```text
Agent Runtime
 -> Runtime API
 -> Spring Control Plane
 -> Long-running Task/Run workflow
 -> Review/Approval
 -> PR/CI integration
 -> Observable, auditable, recoverable platform
```

The original V1 gap was connecting the already-built boundaries to a real GitHub repository flow:

```text
real GitHub Issue webhook
 -> real repository workspace
 -> Python runtime patch
 -> patch branch / commit / push
 -> real PR
 -> GitHub Actions workflow_run writeback
```

That real target-repository vertical slice has now been validated once against `https://github.com/ZhihaoTie/CodeAgent.git`, producing a pull request, GitHub Actions CI run, and final platform `SUCCEEDED` status. The next work should therefore focus on two things: preserving reproducible evidence for V1, and expanding V2 fault-injection reliability evidence rather than broad new feature expansion.

## Current V1 Progress

Started implementation:

```text
Python internal runtime API
Spring Boot control-plane skeleton
Task / Run / Review domain model
PostgreSQL/JPA persistence model
Run event model and live single-node SSE endpoint
Control-plane RuntimeClient for Python execution API
Repository port with JPA-backed implementation
Codex-like review decisions: APPROVE / REQUEST_CHANGES / REJECT / AUTHORIZE_PR; REQUEST_CHANGES now drives a REVISING runtime pass and returns to NEEDS_REVIEW after revised verification succeeds
Local PostgreSQL Docker Compose service
Task idempotency key for duplicate submission / webhook replay protection, with service tests and a duplicate issue webhook smoke script
GitHub Issue webhook receiver with repository metadata, idempotency key, and configurable default verification command
Configurable bounded async worker for runtime submission
Scheduled runtime poller for RUNNING -> NEEDS_REVIEW / FAILED status writeback
Run timeout handling for stuck runtime executions, with a stuck-runtime timeout smoke script
Runtime submit retry policy for transient execution-plane failures, with configurable max attempts and backoff
Startup recovery for persisted QUEUED runs after worker crash / service restart, plus `POST /api/runs/recover-queued` for explicit operational recovery
Authorization-gated ResultPublisher boundary with no-op PR publisher
Config-gated GitHub ResultPublisher skeleton for future real PR creation
Patch artifact model for diff / tests / changed files / trajectory evidence
Deterministic local control-plane smoke demo: task -> review -> noop PR
Deterministic smoke demo now also drives GitHub `workflow_run` CI writeback from PR_CREATED -> CI_RUNNING -> SUCCEEDED
Smoke Spring profile: local demos can run with an in-memory H2 database, noop publisher, short polling, quieter SQL logging, and fake runtime URL without requiring PostgreSQL
Operational health endpoint: `/api/health` reports database connectivity, Python runtime reachability, publisher mode, workspace root, and whether GitHub webhook signature verification is required
Configuration preflight endpoint: `/api/config/preflight` reports whether real GitHub publishing is configured without exposing token values
Target repository REST smoke script: `demos/run_target_repo_rest_smoke.py` submits `https://github.com/ZhihaoTie/CodeAgent.git` through the real task intake path
Target repository issue webhook smoke script: `demos/run_target_repo_issue_webhook_smoke.py` submits the same target through `/api/webhooks/github` with GitHub-style `issues` headers and payload
Duplicate issue webhook smoke script: `demos/run_duplicate_issue_webhook_smoke.py` replays the same `X-GitHub-Delivery` twice and asserts both responses return the same run id
Timeout smoke script: `demos/run_timeout_smoke.py` runs against a fake runtime that never leaves `RUNNING` and verifies the control plane marks the run `FAILED` with a timeout reason
Duplicate workflow_run smoke script: `demos/run_duplicate_workflow_run_smoke.py` replays the same CI webhook and verifies final status/evidence remains idempotent
Runtime submit retry smoke script: `demos/run_runtime_submit_retry_smoke.py` runs against a fake runtime that returns transient 503 failures before accepting the run
Concurrency-limit smoke script: `demos/run_concurrency_limit_smoke.py` runs against a blocking fake runtime and verifies worker submissions do not exceed the configured pool size
Run summary endpoint: `/api/runs/summary` reports total runs, counts by status, and the 10 most recently updated runs for lightweight dashboard/readiness views
Run cancellation endpoint: `/api/runs/{runId}/cancel` marks non-terminal runs as `CANCELLED`, records a cancellation event, and avoids submitting already-cancelled queued runs to the runtime
Run timeline endpoint: `/api/runs/{runId}/timeline` combines persisted run events and review decisions into a lightweight audit trail
Run artifact endpoint: `/api/runs/{runId}/artifact` exposes patch/test evidence separately from the full run object for review and debugging
Task execution metadata path: repository URL/full name, base branch, workspace root, verification command, external task id, and result callback URL can persist on Task and flow into the Python runtime/control-plane workflow
WorkspacePreparer boundary with local Git workspace preparation: explicit workspace roots are validated, repository URLs can be cloned into a managed workspace root, base branches can be checked out, and workspace preparation failures stop the run before Python runtime submission
Execution workspace tracking on Run plus local Git diff artifact collection: after runtime completion, the control plane can collect `git diff --binary` and `git status --porcelain` from the prepared workspace to strengthen or backfill patch evidence
PatchBranchPreparer boundary: after human `AUTHORIZE_PR`, the control plane prepares and records a deterministic local patch branch such as `codeagentx/run-{runId}` before invoking the PR publisher
PatchCommitter boundary: after patch branch preparation, the control plane stages workspace changes, creates a deterministic `CodeAgent-X run {runId}` commit, records the commit SHA, and includes it in PR evidence
PatchPusher boundary: after local patch commit creation, the control plane pushes `HEAD:{patchBranch}` to a configurable remote, records the pushed ref, and only then invokes the PR publisher
Multi-repository GitHub publishing: PR creation now receives both Run and Task context, prefers Task `repositoryFullName` and `baseBranch`, and falls back to global GitHub configuration only when task metadata is absent
GitHub workflow_run CI writeback: workflow run webhooks are matched by `head_branch == patchBranch`, moving runs through `CI_RUNNING`, `SUCCEEDED`, or `FAILED`; duplicate CI writebacks do not duplicate final-text evidence
GitHub webhook signature verification: optional HMAC-SHA256 validation is enforced when `CODEAGENTX_GITHUB_WEBHOOK_SECRET` is configured, while local demos remain frictionless when it is unset
Generic REST adapter endpoint: `POST /api/adapters/generic/tasks` accepts non-GitHub external tasks, maps them into the same `TaskExecutionSpec`, stores external task/callback metadata, and deliberately leaves workspace ownership to the control plane.
Basic request correlation: every control-plane HTTP response includes `X-Request-Id`, incoming request ids are echoed, missing ids are generated, and logs include MDC `request_id`.
Basic metrics endpoint: `/api/metrics` exposes run totals, status counts, active/terminal run counts, worker limits, runtime base URL, publisher mode, and workspace root for lightweight operational visibility.
```

Current local validation:

```text
Python runtime service tests pass.
Python full unit test suite passes: 278 tests with py -3.13 -B -m unittest discover -s tests -v.
Spring Boot control-plane compiles and passes 56 Maven tests on JDK 17, covering workflow state transitions, review action gates, API conflict responses, JPA persistence, GitHub issue/webhook parsing, CI webhook idempotency and terminal-state protection, runtime submit retry, timeout recovery, request correlation, basic metrics, and local Git publishing helpers.
Latest suite-v0 ablation validation: run `ablation-20260825T052003Z-2e3401b1` completed 20 local tasks x 9 variants = 180 task runs; every configured variant resolved 20/20 local fixture tasks. Private audit artifacts are stored under `.codeagentx/benchmark-suite-v0-full/`.
Latest control-plane validation: Maven test suite passed with `mvn test`; workflow tests cover REQUEST_CHANGES -> REVISING -> NEEDS_REVIEW.
Latest local smoke validation: `mvn spring-boot:run "-Dspring-boot.run.profiles=smoke"` plus `py -3.13 -B demos/run_control_plane_smoke.py` reached `SUCCEEDED`.
```

### V1: End-to-End Business Loop

Goal: prove the real vertical slice.

The first milestone is one real GitHub issue becoming one real pull request, with CI validation and status writeback.

Scope:

```text
Python internal runtime API
Spring Boot project skeleton
Task / Run / Review data model
PostgreSQL persistence
Async worker
SSE event stream
GitHub webhook receiver
GitHub PR creation
Review / approval API
Docker Compose local environment
README workflow documentation
```

Success condition:

```text
A GitHub issue triggers a task.
The Java control plane creates and tracks a run.
The Python runtime modifies code and runs verification.
The system exposes patch evidence for review.
A human authorizes PR creation.
GitHub Actions runs CI.
The platform records the final status.
```

### V2: Reliability and Recovery

Goal: prove the system handles realistic agent-platform failures.

Scope:

```text
Webhook idempotency
Run idempotency
Worker crash recovery
Timeout handling
Retry policy
Concurrent task limit
Run cancellation
Duplicate event handling
Fault injection tests
```

Reliability evidence:

```text
The same webhook replayed many times creates one task.
A worker crash does not permanently lose a running task.
An agent timeout does not leave the run stuck forever.
Concurrent tasks are bounded by a configured limit.
Failure reasons are persisted and inspectable.
```

### V3: Platform Completeness

Goal: make the system feel like a platform that can keep evolving.

Scope:

```text
Metrics
Structured logs
Health checks / request correlation / basic metrics
Admin dashboard
Redis / queue if needed
Lease / heartbeat if needed
Generic adapters
Stronger GitHub App permission model
Docker sandbox hardening
Deployment documentation
```

V3 should not block V1. The project should first prove the real business loop, then add platform hardening.


## Execution Evidence Matrix

The project should be read through a small evidence matrix rather than a feature list:

| Evidence area | What it proves | Current artifact |
| --- | --- | --- |
| Runtime capability | The Python agent can inspect, edit, verify, reflect, retry, and report inside a repository | Python unit tests, deterministic 3-minute demo, completed suite-v0 ablation run |
| Business vertical slice | A real development task can enter through GitHub webhook or Generic REST and return as PR/CI status | `docs/e2e-github-target.md`, target repo PR #1, CI writeback record, `/api/adapters/generic/tasks` |
| Review control | Human feedback can approve, reject, request changes, or authorize PR publication | `APPROVE`, `REQUEST_CHANGES`, `REJECT`, `AUTHORIZE_PR` workflow |
| Idempotency | Duplicate delivery does not create duplicate work | `demos/run_duplicate_issue_webhook_smoke.py` |
| Duplicate event handling | Duplicate CI webhooks do not duplicate status evidence | `demos/run_duplicate_workflow_run_smoke.py` |
| Timeout recovery | A stuck runtime does not leave a run hanging forever | `demos/run_timeout_smoke.py` |
| Runtime submit retry | Transient execution-plane submission failures can recover without failing the run | `demos/run_runtime_submit_retry_smoke.py` |
| Concurrency control | Runtime submissions are bounded by configured worker limits | `demos/run_concurrency_limit_smoke.py` |
| Queued-run recovery | Queued runs can be recovered after crash/restart | startup recovery plus `POST /api/runs/recover-queued` |
| Auditability | Runs expose timeline, events, patch artifact, status, and failure reason | `/api/runs/{id}/timeline`, `/events`, `/artifact`, `/summary` |

This keeps the project grounded: every new capability should either advance the business loop, improve reliability, or make evidence easier to audit.

## Evidence Strategy

The project should keep three kinds of evidence.

### Agent Capability Evidence

Shows that the Python runtime can perform repository-level engineering tasks.

```text
Runtime unit tests
suite-v0 benchmark
Ablation evaluation
SWE-bench evaluator integration
Trajectory reports
```

### Engineering Reliability Evidence

Shows that the platform can survive common production failures.

```text
Duplicate webhook tests
Timeout tests
Worker crash recovery tests
Concurrency limit tests
Restart recovery tests
Idempotency tests
```

### Business Loop Evidence

Shows that the platform can enter a real development workflow.

```text
Real GitHub Issue
Real Agent Run
Real Proposed Patch
Real Interactive Review
Real Pull Request
Real GitHub Actions CI
Recorded status writeback
```

## Project Boundaries

CodeAgent-X 2.0 should not become:

```text
A chatbot
A generic agent framework with no concrete workflow
A high-concurrency system before the vertical slice works
A pile of middleware without a working issue-to-PR loop
A system where the model can directly change remote state without review
```

It should focus on:

```text
Real task entry
Async long-running task management
Controlled agent execution
Reviewable patches
Feedback-driven revisions
Human-authorized PR creation
CI-backed validation
Recoverable failures
Auditable trajectories
```

## Final Questions the Project Must Answer

```text
How does work enter the system?
GitHub Issue / Webhook / REST

How does the agent execute?
Python Runtime / Sandbox / Tool Calling

How are long-running tasks managed?
Task / Run / DB / Async Worker / SSE

How does a human intervene?
Codex-like Review / Request Changes / Approval

How are failures handled?
Idempotency / Timeout / Retry / Recovery / Concurrency Limit

How does the result return to the business workflow?
PR / CI / Status Callback / Trajectory Report
```

## Final Target

The final target is to upgrade CodeAgent-X from:

```text
I implemented a software engineering agent runtime.
```

to:

```text
I implemented a reviewable, recoverable, verifiable, deployable software engineering agent platform that can be embedded into a real development workflow.
```

Latest real target repository E2E validation:

```text
Target repository: https://github.com/ZhihaoTie/CodeAgent.git
Run ID: 51c1145d-e825-4815-ac95-7c047ef73e78
Patch branch: codeagentx/run-51c1145d-e825-4815-ac95-7c047ef73e78
Patch commit: 24894da3619e57a0d28c31a926cd5233367fc387
Pull request: https://github.com/ZhihaoTie/CodeAgent/pull/1
CI run: https://github.com/ZhihaoTie/CodeAgent/actions/runs/32764128036
Final platform status: SUCCEEDED
```
