# Deployment Validation Record

This document records the current production-like local deployment validation for CodeAgent-X. It is not a benchmark score and does not claim public SWE-bench resolution results. Its purpose is to show that the platform control plane, execution plane, persistence layer, and external callback path can run together as an auditable single-node system.

## Validation scope

Validated on a local Docker Compose deployment:

```text
Spring Boot Control Plane
PostgreSQL
Python Agent Runtime
Shared /workspaces volume
Generic REST task intake
Result callback delivery
Health / preflight / metrics surfaces
Restart recovery smoke path
```

The Python runtime and PostgreSQL are kept internal to the Compose network. Only the Spring Boot control-plane API is published to the host.

## Current Compose topology

```text
Host
  |
  |  http://127.0.0.1:8080
  v
codeagentx-control-plane  healthy
  |-- JDBC --> codeagentx-postgres  healthy
  |-- HTTP --> codeagentx-runtime   healthy
  '-- volume: /workspaces
```

Current service state observed after rebuilding and restarting the local Compose deployment:

```text
codeagentx-control-plane   Up, healthy, 0.0.0.0:8080->8080
codeagentx-postgres        Up, healthy
codeagentx-runtime         Up, healthy
```

## Health / preflight / metrics smoke

Command:

```bash
python demos/run_compose_smoke.py
```

Observed result:

```text
health.status = ok
health.database = ok
health.runtime = ok
health.runtimeBaseUrl = http://runtime:8765
health.workspaceRoot = /workspaces
preflightStatus = ready
metrics.runs present
metrics.worker present
metrics.runtime present
metrics.publisher present
metrics.callbacks present
```

This validates that the public control-plane endpoint can reach both internal dependencies and exposes enough operational state for deployment checks.

## Restart recovery smoke

Command:

```bash
python demos/run_compose_restart_smoke.py
```

The restart smoke restarts the Compose services, waits for `/api/health`, and then reuses `demos/run_compose_smoke.py` to verify health, preflight, metrics, and request-id behavior after recovery.

This validates the first production-readiness property for the platform shell: a single-node restart does not leave the deployment in an unrecoverable state.

## Generic REST callback smoke

Command:

```bash
CODEAGENTX_CALLBACKS_ENABLED=true docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build
python demos/run_compose_generic_callback_smoke.py
```

The smoke creates a real Task/Run through the Generic REST adapter, but uses bounded runtime overrides:

```json
{
  "provider": "mock",
  "model": "mock-model",
  "maxTurns": 1,
  "maxRunSeconds": 15.0,
  "permissionMode": "auto"
}
```

This avoids paid model calls and avoids PR creation while still exercising the platform path.

Observed result from the callback smoke:

```text
accepted.status = QUEUED
firstCallback.status = QUEUED
finalRun.status = NEEDS_REVIEW
finalCallback.status = NEEDS_REVIEW
finalRun.runtimeRunId = generated
callback delivery records include DELIVERED outcomes for QUEUED/RUNNING/NEEDS_REVIEW updates
audit summary reports hasCallback = true
```

This validates the business-control path:

```text
External task
 -> Generic REST Adapter
 -> Task / Run persistence
 -> Async workflow
 -> Python Runtime submission
 -> Runtime completion refresh
 -> Reviewable result
 -> External callback writeback
 -> Callback delivery record
 -> Execution audit API
```

## Runtime override contract

Generic REST tasks can now provide bounded execution-plane overrides:

```text
provider
model
maxTurns
maxRunSeconds
permissionMode
```

These fields flow through:

```text
GenericTaskRequest
 -> TaskExecutionSpec
 -> TaskRecord
 -> RunWorkflowService
 -> RuntimeRunRequest
 -> Python Runtime API payload
```

Workspace control remains intentionally owned by the control plane. The Generic REST adapter does not trust externally supplied `workspaceRoot` values.

## Automated test evidence

Control-plane Maven tests passed on JDK 17:

```text
tests=58 failures=0 errors=0 skipped=0
```

Covered areas include workflow state transitions, review gates, runtime submission, timeout/retry/recovery behavior, webhook idempotency, CI writeback idempotency, request correlation, metrics, callback notifier behavior, and the Generic REST runtime override path.

## Public-safety check

Before committing this validation work, the public workspace was scanned excluding private `.codeagentx/` and build outputs for private career-material wording and GitHub personal-access-token prefixes.

No matches were found.

## What this does not claim

This validation record does not claim:

```text
public SWE-bench resolved score
large-scale distributed scheduling
Kubernetes production deployment
unbounded autonomous merge capability
human-free PR creation or merge approval
```

The current claim is narrower and stronger:

> CodeAgent-X can run as a production-like single-node software engineering Agent platform with a Spring Boot control plane, Python execution runtime, PostgreSQL persistence, Docker Compose deployment, Generic REST task intake, asynchronous run management, reviewable runtime results, operational health surfaces, and external result callbacks.