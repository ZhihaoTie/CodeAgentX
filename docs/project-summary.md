# CodeAgent-X Project Summary

## One-sentence summary

CodeAgent-X is a software-engineering agent system that turns code-repair tasks
into auditable, test-backed patches through a local CLI, a generic REST adapter,
and a GitHub Issue -> Review -> PR workflow.

## What problem it solves

Most coding-agent demos stop at "the model edited a file." CodeAgent-X focuses
on the engineering boundary around that edit:

- how the task enters the system;
- how repository work is isolated;
- how tools are permissioned;
- how test evidence is captured;
- how failures are reflected on and retried;
- how a human reviews the patch;
- how the result can become a pull request;
- how the whole run can be audited later.

## Architecture

CodeAgent-X has two main planes.

### Python execution plane

The Python runtime performs the actual software-engineering work:

- model turn orchestration;
- tool execution;
- file read/write/edit;
- shell execution with risk classification;
- AST and text context retrieval;
- patch transactions and rollback metadata;
- verifier execution;
- structured test-output parsing;
- failure reflection and retry strategy;
- trajectory and benchmark artifacts.

### Java control plane

The Spring Boot control plane provides the platform workflow:

- task and run persistence;
- asynchronous runtime submission;
- status polling and recovery;
- run events, timeline, and audit APIs;
- review decisions;
- GitHub webhook intake;
- GitHub workflow_run CI writeback boundary;
- branch, commit, push, and PR publication boundary;
- Generic REST adapter;
- health, metrics, and configuration preflight.

## User-facing modes

### 1. Local Developer Mode

For one developer working inside a checkout:

```bash
codeagentx doctor
codeagentx init --verify "pytest -q" --yes
codeagentx fix --yes
```

`fix` starts from a failing verifier. It captures the failure output, summarizes
failing tests and likely relevant files, gives that context to the agent, applies
a patch, reruns the verifier, and prints the resulting summary and diff.

This is the mode closest to everyday personal use.

### 2. Generic Integration Mode

For external systems that want to create agent tasks without adopting GitHub
Issues:

```http
POST /api/adapters/generic/tasks
```

This validates CodeAgent-X as a business-system integration boundary. Callers
can submit task metadata, receive callbacks, and inspect audit records while the
control plane owns workspace preparation and execution safety.

### 3. GitHub Platform Mode

For repository workflow integration:

```text
GitHub Issue
 -> webhook
 -> Task / Run
 -> Agent patch
 -> Tests
 -> Human review
 -> Branch / Commit / Push
 -> Pull Request
 -> CI status writeback
```

This mode demonstrates how an agent can fit into a real engineering process
without skipping review or auditability.

## Reliability design

The project includes explicit support for:

- idempotent webhook handling;
- queued-run recovery;
- runtime submit retry;
- stuck-runtime timeout;
- worker concurrency limits;
- request correlation IDs;
- callback delivery tracking;
- deterministic verifier reports;
- patch policy checks;
- rollback metadata for tool edits.

## Final implementation state

Completed:

- Python runtime and local CLI;
- `doctor`, `init`, and verifier-first `fix`;
- Spring Boot control plane;
- Generic REST task adapter;
- GitHub webhook intake;
- review-gated patch publication flow;
- GitHub token-backed branch push implementation;
- Docker Compose deployment topology;
- health, metrics, preflight, audit, artifact, event, and timeline APIs;
- local benchmark and SWE-bench integration path;
- final documentation and scope freeze.

Deferred by design:

- Kubernetes or distributed production orchestration;
- Redis/Kafka queue infrastructure;
- multi-agent orchestration;
- RAG or memory platform expansion;
- IDE plugin or full editor clone;
- admin dashboard;
- additional integrations beyond Generic REST and GitHub.

## Final assessment

CodeAgent-X has enough working surface area to demonstrate a complete
software-engineering agent platform:

```text
Agent Runtime
+ Local Developer UX
+ Business REST Boundary
+ GitHub Workflow Boundary
+ Verification
+ Review
+ Auditability
+ Deployment Path
```

The project should now be frozen except for validation fixes and public-release
polish. Further feature expansion would reduce focus more than it would improve
the core project.
