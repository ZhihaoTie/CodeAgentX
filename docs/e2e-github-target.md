# Real GitHub Target Repository E2E

This document records the reproducible vertical-slice path for running CodeAgent-X against a real GitHub repository.

The purpose is to prove the platform loop:

```text
REST / GitHub task intake
 -> persisted Task / Run
 -> Python runtime execution
 -> patch and test evidence
 -> human authorization
 -> patch branch / commit / push
 -> Pull Request
 -> GitHub Actions CI writeback
 -> final platform status
```

## Target repository role

`https://github.com/ZhihaoTie/CodeAgent.git` is the target/input repository used by the platform demo.

It is not the CodeAgent-X platform repository. CodeAgent-X checks out this repository into a managed runtime workspace, lets the Python execution plane modify it, and then asks the Java control plane to publish the resulting patch back as a pull request.

## Prerequisites

- JDK 17
- Maven
- Python 3.13
- Git
- A GitHub token configured through local environment variables or deployment secrets
- The target repository configured with a GitHub Actions workflow

Do not commit local secret files. `.env` and `.codeagentx/` are intentionally ignored.

## Start the Python runtime

From the project root:

```powershell
py -3.13 -B -m codeagentx.service --host 127.0.0.1 --port 8765
```

## Start the Java control plane

For a local smoke run with H2:

```powershell
cd control-plane
mvn spring-boot:run "-Dspring-boot.run.profiles=smoke"
```

For real GitHub PR publication, configure:

```powershell
$env:CODEAGENTX_PUBLISHER_MODE="github"
$env:CODEAGENTX_GITHUB_TOKEN="..."
$env:CODEAGENTX_GITHUB_BASE_BRANCH="main"
$env:CODEAGENTX_GITHUB_REMOTE_NAME="origin"
$env:CODEAGENTX_GITHUB_DEFAULT_VERIFICATION_COMMAND="py -3.13 -B -m unittest discover -s tests -v"
```

Optionally configure:

```powershell
$env:CODEAGENTX_GITHUB_REPOSITORY="ZhihaoTie/CodeAgent"
```

## Preflight checks

Check service health:

```powershell
Invoke-RestMethod http://127.0.0.1:8080/api/health
```

Check publication readiness without exposing token values:

```powershell
Invoke-RestMethod http://127.0.0.1:8080/api/config/preflight
```

Expected readiness:

```text
runtime reachable
publisherMode github
tokenConfigured true
repositoryConfigured true
status ready
```

## Submit the target repository task

From the project root:

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

The smoke script submits a REST task for the target repository and waits until the run reaches a reviewable or terminal state.

Expected reviewable state:

```text
NEEDS_REVIEW
```

## Authorize publication

When the artifact has a clean diff and passing test report, authorize PR creation:

```powershell
$body = @{
  decision = "AUTHORIZE_PR"
  comment = "Publish this verified patch as a pull request."
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8080/api/runs/{runId}/review" `
  -ContentType "application/json" `
  -Body $body
```

This triggers the control plane to:

```text
prepare deterministic patch branch
stage modified repository files
create patch commit
push branch to origin
create GitHub pull request
record PR URL and patch metadata
```

## CI writeback

GitHub Actions emits a `workflow_run` webhook for the PR branch.

The control plane matches the webhook by:

```text
workflow_run.head_branch == run.patchBranch
```

Expected state transitions:

```text
PR_CREATED -> CI_RUNNING -> SUCCEEDED
```

If running locally without a public webhook receiver, CI writeback can be simulated by posting a local `workflow_run` payload to:

```text
POST /api/webhooks/github
```

## Latest validated evidence

```text
Target repository: https://github.com/ZhihaoTie/CodeAgent.git
Run ID: 51c1145d-e825-4815-ac95-7c047ef73e78
Runtime run ID: 00920fb1-f433-4d77-b28c-825931f21e21
Patch branch: codeagentx/run-51c1145d-e825-4815-ac95-7c047ef73e78
Patch commit: 24894da3619e57a0d28c31a926cd5233367fc387
Pull request: https://github.com/ZhihaoTie/CodeAgent/pull/1
CI run: https://github.com/ZhihaoTie/CodeAgent/actions/runs/32764128036
Final platform status: SUCCEEDED
```

The validated patch changed the target repository implementation and passed:

```powershell
py -3.13 -B -m unittest discover -s tests -v
```

## Artifact hygiene

Runtime-private artifacts such as `.codeagentx/` must not appear as target repository code changes.

The control plane collects patch evidence from the prepared Git workspace and filters private runtime directories from `git status --porcelain` before exposing changed files in run artifacts.

