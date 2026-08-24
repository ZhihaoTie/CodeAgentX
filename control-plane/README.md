# CodeAgent-X Control Plane

This module is the first Spring Boot control-plane slice for CodeAgent-X 2.0.

It manages platform-level tasks, runs, and Codex-like review decisions while delegating repository execution to the Python runtime service.

## Runtime Dependency

Start the Python execution plane first:

```powershell
py -3.13 -B -m codeagentx.service --host 127.0.0.1 --port 8765
```

Then start this Spring Boot service when Maven is available:

```powershell
mvn spring-boot:run
```

This project targets JDK 17.

Task creation is asynchronous at the platform boundary: `POST /api/tasks` persists a task/run and returns `202 Accepted`; a bounded background worker then submits the run to the Python execution plane.

Operational readiness can be checked with:

```powershell
curl http://127.0.0.1:8080/api/health
```

The health response reports database connectivity, Python runtime reachability, runtime base URL, publisher mode, workspace root, and whether GitHub webhook signature verification is required.

Configuration readiness for real GitHub publishing can be checked with:

```powershell
curl http://127.0.0.1:8080/api/config/preflight
```

The preflight response reports whether the GitHub token, base branch, remote name, optional global repository, and webhook secret are configured without exposing secret values. If no global repository is configured, real GitHub publishing can still be ready as long as each task provides `repositoryFullName`; the endpoint returns that case as a warning.

Run state can be summarized with:

```powershell
curl http://127.0.0.1:8080/api/runs/summary
```

The summary response includes total runs, counts by status, and the 10 most recently updated runs with only lightweight metadata.

`POST /api/tasks` can also carry execution metadata that will be persisted on the task and forwarded to the Python runtime:

```json
{
  "source": "rest",
  "title": "Fix failing parser test",
  "body": "Parser fails on empty input.",
  "idempotencyKey": "manual-parser-001",
  "repositoryUrl": "https://github.com/acme/repo.git",
  "repositoryFullName": "acme/repo",
  "baseBranch": "main",
  "workspaceRoot": "D:\\workspaces\\repo",
  "verificationCommand": "py -3.13 -B -m unittest discover -s tests -v"
}
```

This is the first explicit boundary between business intake and execution context: the control plane records which repository/task is being requested, while the Python runtime receives the concrete workspace and verification command it needs to execute safely.

Before submitting to the Python runtime, the control plane now runs a `WorkspacePreparer` boundary:

```text
explicit workspaceRoot -> validate that it exists -> pass to Python runtime
repositoryUrl only     -> clone into managed workspace root -> checkout baseBranch -> pass to Python runtime
preparation failure    -> mark run FAILED before runtime submission
```

The managed workspace root defaults to:

```text
../.codeagentx/control-plane/workspaces
```

Override it with:

```powershell
$env:CODEAGENTX_WORKSPACE_ROOT="D:\codeagentx-workspaces"
```

Runtime completion is also observed asynchronously. A scheduled poller refreshes `RUNNING` runs from the Python execution plane every 5 seconds by default. Override it with:

```powershell
$env:CODEAGENTX_RUNTIME_POLL_DELAY_MS="2000"
```

Long-running agent executions are failed by timeout instead of being left in `RUNNING` forever. The default timeout is 30 minutes:

```powershell
$env:CODEAGENTX_RUNTIME_RUN_TIMEOUT_MS="1800000"
```

On startup, the control plane performs a simple crash recovery pass: persisted `QUEUED` runs without a Python runtime id are resubmitted to the runtime worker. Persisted `RUNNING` runs with a runtime id are handled by the scheduled poller.

PR publication is behind explicit human authorization. `AUTHORIZE_PR` moves the run through `PR_CREATING` and then calls a `ResultPublisher`. The current V1 implementation uses a no-op publisher that records a deterministic `noop://pull-requests/{runId}` URL; a real GitHub publisher will replace this boundary later without giving the agent direct remote write authority.

To switch the publishing boundary to the GitHub implementation:

```powershell
$env:CODEAGENTX_PUBLISHER_MODE="github"
$env:CODEAGENTX_GITHUB_TOKEN="<token>"
$env:CODEAGENTX_GITHUB_REPOSITORY="owner/repo"
$env:CODEAGENTX_GITHUB_BASE_BRANCH="main"
$env:CODEAGENTX_GITHUB_WEBHOOK_SECRET="<github-webhook-secret>"
```

For GitHub webhook or REST tasks that carry repository metadata, PR publishing prefers task-level values:

```text
repositoryFullName -> GitHub PR target repository
baseBranch         -> GitHub PR base branch
```

If a task does not provide these fields, the publisher falls back to `CODEAGENTX_GITHUB_REPOSITORY` and `CODEAGENTX_GITHUB_BASE_BRANCH`. This keeps local demos simple while allowing one control plane to route runs for multiple repositories.

After human `AUTHORIZE_PR`, the control plane now runs a `PatchBranchPreparer` boundary before calling the publisher. The local implementation checks out a deterministic branch in the execution workspace:

```text
codeagentx/run-{runId}
```

The branch name is persisted on the run as `patchBranch` and used as the GitHub PR head branch.

After the local branch is prepared, the control plane runs a `PatchCommitter` boundary. The local implementation stages workspace changes and creates a deterministic commit:

```text
CodeAgent-X run {runId}
```

The resulting commit SHA is persisted on the run as `patchCommitSha` and included in the PR body.

After the local commit is created, the control plane runs a `PatchPusher` boundary. The local implementation pushes the current `HEAD` to the configured remote and branch:

```text
git push {remoteName} HEAD:{patchBranch}
```

The pushed ref is persisted on the run as `patchPushedRef` and included in the PR body. The remote name defaults to `origin`:

```powershell
$env:CODEAGENTX_GITHUB_REMOTE_NAME="origin"
```

Runtime results can now include a structured patch artifact alongside `finalText`:

```text
patchDiff
testReport
changedFiles
trajectoryReportPath
```

These fields are persisted on the run and included in the GitHub PR body by the publisher boundary.

The control plane also records the concrete `executionWorkspaceRoot` on each run when workspace preparation succeeds. When a runtime run reaches a terminal state, it attempts to collect repository-level patch evidence from that workspace:

```text
git diff --binary
git status --porcelain
```

If Git diff collection succeeds, the collected diff and changed-file status are used to strengthen or backfill the run's patch artifact. If collection fails, the control plane keeps the runtime-provided artifact and does not fail an otherwise completed run.

## Database

The control plane persists tasks, runs, review records, and run events with Spring Data JPA.

Default local PostgreSQL settings:

```text
url:      jdbc:postgresql://localhost:5432/codeagentx
username: codeagentx
password: codeagentx
```

You can start the local database from the repository root:

```powershell
docker compose up -d postgres
```

Or override the connection:

```powershell
$env:CODEAGENTX_DB_URL="jdbc:postgresql://localhost:5432/codeagentx"
$env:CODEAGENTX_DB_USERNAME="codeagentx"
$env:CODEAGENTX_DB_PASSWORD="codeagentx"
```

Tests use H2 through `@DataJpaTest`, so PostgreSQL is not required for `mvn test`.

## Initial API

```text
POST /api/tasks
POST /api/webhooks/github
GET  /api/runs/{runId}
GET  /api/runs/{runId}/events
POST /api/runs/{runId}/refresh
POST /api/runs/{runId}/review
```

`POST /api/runs/{runId}/review` accepts:

```json
{
  "decision": "REQUEST_CHANGES",
  "comment": "Keep the patch, but add one boundary test."
}
```

`POST /api/tasks` may include an optional `idempotencyKey`. Reusing the same key returns the original run instead of starting a duplicate runtime execution. This is the first reliability hook for webhook replay handling.

`POST /api/webhooks/github` accepts GitHub `issues` webhook events for `opened`, `reopened`, and `labeled` actions. It uses `X-GitHub-Delivery` as the idempotency source, so replayed deliveries do not start duplicate agent runs. The webhook parser also captures repository `full_name`, `clone_url`/`html_url`, and `default_branch` so later sandbox and publisher stages know which repo and base branch the issue belongs to.

The same endpoint also accepts GitHub `workflow_run` events for CI status writeback. The V1 matcher uses:

```text
workflow_run.head_branch == run.patchBranch
```

Status mapping:

```text
non-completed workflow_run -> CI_RUNNING
completed + success        -> SUCCEEDED
completed + other result   -> FAILED
```

Supported decisions:

```text
APPROVE
REQUEST_CHANGES
REJECT
AUTHORIZE_PR
```

Runs can also be cancelled explicitly:

```powershell
curl -X POST http://127.0.0.1:8080/api/runs/{runId}/cancel `
  -H "Content-Type: application/json" `
  -d "{\"reason\":\"No longer needed\"}"
```

Cancellation is idempotent for terminal runs; runs that already reached `SUCCEEDED`, `FAILED`, or `CANCELLED` are not changed.

This is intentionally still a V1 vertical slice. PostgreSQL/JPA persistence, GitHub issue webhook intake, optional GitHub webhook signature verification, GitHub workflow_run CI writeback, task idempotency, repository execution metadata, workspace preparation boundary, execution workspace tracking, Git diff artifact collection, local patch branch preparation, local patch commit creation, remote patch push boundary, multi-repository GitHub PR target selection, bounded async runtime submission, live single-node SSE event streaming, timeout handling, startup recovery, and authorization-gated PR publishing boundary are in place. Complete GitHub PR creation depends on configuring the GitHub publisher token/repository and a pushable remote.
`GET /api/runs/{runId}/events` first emits persisted events already recorded for the run, then stays open for new in-process events.

For a point-in-time audit view without opening SSE:

```powershell
curl http://127.0.0.1:8080/api/runs/{runId}/timeline
```

The timeline response combines run events and review decisions into a lightweight ordered audit trail.

For patch/test evidence:

```powershell
curl http://127.0.0.1:8080/api/runs/{runId}/artifact
```

The artifact response includes diff text, changed files, test report, trajectory report path, patch branch, commit SHA, pushed ref, and pull request URL when available.

## Local Smoke Demo

Start the control plane, then run the deterministic smoke driver from the repository root:

```powershell
cd control-plane
mvn spring-boot:run -Dspring-boot.run.profiles=smoke
```

The `smoke` profile uses an in-memory H2 database, the noop publisher, a short runtime poll interval, and the fake runtime URL used by the demo. The default profile still targets PostgreSQL.

In a second terminal:

```powershell
py -3.13 -B demos/run_control_plane_smoke.py
```

The script starts a fake runtime on `127.0.0.1:8765`, creates a task through the control plane, waits for `NEEDS_REVIEW`, authorizes publication, expects a noop `PR_CREATED` result, then sends deterministic GitHub `workflow_run` webhooks to drive CI writeback from `CI_RUNNING` to `SUCCEEDED`.
