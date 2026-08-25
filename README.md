# CodeAgent-X

CodeAgent-X is an autonomous software engineering agent runtime and control-plane prototype.

The project is not a chatbot wrapper around an LLM. Its goal is to make model-driven code changes controllable, reviewable, recoverable, and auditable inside real repositories.

At the runtime level, CodeAgent-X already supports the core software-engineering agent loop:

```text
Task
 -> Plan
 -> Tool Call
 -> Repository Edit
 -> Verification
 -> Failure Reflection
 -> Retry
 -> Trajectory Report
```

The 2.0 direction embeds that runtime into a real development workflow:

```text
GitHub Issue
 -> Task / Run
 -> Python Agent Runtime
 -> Patch + Test Report
 -> Human Review
 -> Pull Request
 -> CI Status Writeback
```

## Architecture

CodeAgent-X is split into two planes.

### Python execution plane

The Python runtime performs the actual repository work:

- agent loop and run state
- tool execution
- file read/write/edit
- grep/glob/AST context retrieval
- shell execution with risk classification
- workspace safety checks
- patch transactions and rollback metadata
- outcome verification
- failure reflection and retry strategy
- trajectory storage
- benchmark and SWE-bench adapter support

Main package:

```text
codeagentx/
```

### Java control plane

The Spring Boot control plane manages business workflow around the runtime:

- task and run persistence
- asynchronous runtime submission
- status polling
- run events and timeline
- artifact exposure
- review decisions
- GitHub issue webhook intake
- GitHub workflow_run CI writeback
- PR publication boundary
- health and configuration preflight endpoints
- local smoke profile

Main module:

```text
control-plane/
```

## Current status

Implemented and validated:

- Python runtime unit test suite: 278 tests passed locally.
- Deterministic 3-minute runtime demo: `Task -> Plan -> Read -> Patch -> Test -> Failure -> Reflection -> Retry -> Success -> Report`.
- Spring Boot control-plane slice with task/run workflow, review, webhook intake, generic REST adapter, CI writeback, artifact, timeline, request correlation, metrics, health, and config preflight.
- Control-plane Maven validation: 56 tests passed on JDK 17.
- Local benchmark framework with a completed suite-v0 ablation run: 20 local tasks x 9 variants = 180 task runs, with each configured variant resolving 20/20 local fixture tasks in the latest run.
- SWE-bench adapter and official evaluator integration path.

Evaluation claims are intentionally conservative. The local suite and ablation harness are project evidence for this repository's fixture tasks; current public documentation does not claim an official SWE-bench resolved score.

## Quick start: Python runtime

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the Python test suite:

```bash
python -m unittest discover -s tests -v
```

Run the deterministic demo:

```bash
python demos/run_3min_demo.py
```

Start the runtime service:

```bash
python -m codeagentx.service --host 127.0.0.1 --port 8765
```

## Quick start: control plane

The control plane requires JDK 17 and Maven.

Run tests:

```bash
cd control-plane
mvn test
```

Start the Spring Boot service:

```bash
cd control-plane
mvn spring-boot:run
```

For local smoke testing without PostgreSQL, use the smoke profile:

```powershell
cd control-plane
mvn spring-boot:run "-Dspring-boot.run.profiles=smoke"
```

Then run:

```powershell
py -3.13 -B demos/run_control_plane_smoke.py
```

Submit the real GitHub target repository through the generic REST task path after starting the Python runtime and control plane:

```powershell
py -3.13 -B demos/run_target_repo_rest_smoke.py
```

Submit the same target repository through the GitHub issue webhook path:

```powershell
py -3.13 -B demos/run_target_repo_issue_webhook_smoke.py
```

Replay the same GitHub issue delivery twice to verify webhook idempotency:

```powershell
py -3.13 -B demos/run_duplicate_issue_webhook_smoke.py
```

Replay the same GitHub workflow_run delivery twice to verify CI writeback idempotency:

```powershell
py -3.13 -B demos/run_duplicate_workflow_run_smoke.py
```

Run the stuck-runtime timeout smoke with a short control-plane timeout:

```powershell
py -3.13 -B demos/run_timeout_smoke.py
```

Run the runtime submit retry smoke with retry attempts enabled:

```powershell
$env:CODEAGENTX_RUNTIME_SUBMIT_MAX_ATTEMPTS="3"
$env:CODEAGENTX_RUNTIME_SUBMIT_RETRY_BACKOFF_MS="100"
py -3.13 -B demos/run_runtime_submit_retry_smoke.py
```

Run the worker concurrency-limit smoke with the control-plane worker size set to 1:

```powershell
$env:CODEAGENTX_WORKER_CORE_POOL_SIZE="1"
$env:CODEAGENTX_WORKER_MAX_POOL_SIZE="1"
$env:CODEAGENTX_WORKER_QUEUE_CAPACITY="10"
```

```powershell
py -3.13 -B demos/run_concurrency_limit_smoke.py
```


## Evidence checklist

| Area | Command or artifact |
| --- | --- |
| Python runtime tests | `py -3.13 -B -m unittest discover -s tests -v` |
| Runtime demo | `py -3.13 -B demos/run_3min_demo.py` |
| Control-plane tests | `cd control-plane; mvn test` |
| Local control-plane smoke | `py -3.13 -B demos/run_control_plane_smoke.py` |
| Target REST smoke | `py -3.13 -B demos/run_target_repo_rest_smoke.py` |
| Target GitHub issue webhook smoke | `py -3.13 -B demos/run_target_repo_issue_webhook_smoke.py` |
| Duplicate webhook idempotency | `py -3.13 -B demos/run_duplicate_issue_webhook_smoke.py` |
| Duplicate CI webhook idempotency | `py -3.13 -B demos/run_duplicate_workflow_run_smoke.py` |
| Stuck runtime timeout | `py -3.13 -B demos/run_timeout_smoke.py` |
| Runtime submit retry | `py -3.13 -B demos/run_runtime_submit_retry_smoke.py` |
| Worker concurrency limit | `py -3.13 -B demos/run_concurrency_limit_smoke.py` |
| Real target-repository E2E record | `docs/e2e-github-target.md` |

The reliability smokes use fake runtimes where appropriate. This makes the failure modes deterministic and locally reproducible instead of depending on live external failures.

## Important endpoints

```text
POST /api/tasks
POST /api/adapters/generic/tasks
GET  /api/runs/{runId}
POST /api/runs/{runId}/refresh
POST /api/runs/recover-queued
POST /api/runs/{runId}/review
POST /api/runs/{runId}/cancel
GET  /api/runs/{runId}/events
GET  /api/runs/{runId}/timeline
GET  /api/runs/{runId}/artifact
GET  /api/runs/summary
GET  /api/metrics
GET  /api/health
GET  /api/config/preflight
POST /api/webhooks/github
```

The generic REST adapter is the second task-source boundary next to GitHub webhooks. It accepts external task metadata such as `externalTaskId` and `resultCallbackUrl`, converts the request into the same internal `TaskExecutionSpec`, and deliberately does not accept external workspace control; workspace preparation remains owned by the control plane.

Every control-plane HTTP request returns `X-Request-Id`. If the caller provides the header, CodeAgent-X echoes it; otherwise the control plane generates one and places it in the logging MDC as `request_id` for basic cross-request troubleshooting.

`/api/metrics` exposes a lightweight operational snapshot with run counts, status distribution, active/terminal run totals, worker limits, runtime base URL, publisher mode, and workspace root.

## GitHub publishing configuration

The real GitHub PR boundary is configuration-gated.

Set the publisher mode and token through local environment variables or deployment secrets:

```powershell
$env:CODEAGENTX_PUBLISHER_MODE="github"
$env:CODEAGENTX_GITHUB_TOKEN="..."
$env:CODEAGENTX_GITHUB_BASE_BRANCH="main"
$env:CODEAGENTX_GITHUB_REMOTE_NAME="origin"
```

Optionally configure a global repository:

```powershell
$env:CODEAGENTX_GITHUB_REPOSITORY="owner/repo"
```

If no global repository is configured, each task can provide `repositoryFullName`.

Check readiness without exposing secret values:

```bash
curl http://127.0.0.1:8080/api/config/preflight
```

## Repository layout

```text
codeagentx/                    Python agent runtime
control-plane/                 Spring Boot business/control plane
demos/                         deterministic local demos
benchmarks/                    local benchmark specs and fixtures
tests/                         Python unit tests
docs/codeagentx-2.0-plan.md    public 2.0 project plan
docs/e2e-github-target.md      real target-repository E2E runbook
```

Private runtime outputs, local reports, API keys, benchmark artifacts, and temporary workspaces are excluded through `.gitignore`.

## Project direction

The next major milestone is a real vertical slice:

```text
GitHub Issue
 -> webhook
 -> persisted Task / Run
 -> asynchronous Python runtime execution
 -> patch and test evidence
 -> explicit review authorization
 -> branch / commit / push
 -> Pull Request
 -> GitHub Actions CI writeback
```

This turns CodeAgent-X from a standalone agent runtime into a software engineering agent platform that can be embedded into a real development workflow.
