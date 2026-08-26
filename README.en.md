# CodeAgent-X

[中文](README.md) | English

**Turn a software task into a verifiable, reviewable, and traceable code change.**

CodeAgent-X is a software-engineering agent runtime and workflow platform for real repositories. It goes beyond model-driven code editing by organizing execution, verification, failure recovery, human review, pull requests, and CI status into one auditable loop.

It is not another chat interface and is not intended to replace Cursor or Codex. Individual developers can use the lightweight local CLI. Teams that need GitHub automation, approval gates, audit trails, and asynchronous execution can deploy the server-side control plane.

```text
GitHub Issue
    ↓
Webhook → Task / Run → Agent edits code → Automated tests
    ↓
Patch and audit trail → Human review → Pull Request → GitHub Actions CI
    ↓
                                      CI writeback → SUCCEEDED
```

## Why CodeAgent-X

- **Start from the failure**: consume a failing verifier instead of asking users to restate a known error.
- **Verification first**: rerun the same command after editing and store a structured test report.
- **Safe changes**: enforce workspace boundaries and record patch, rollback, and audit metadata.
- **Human approval**: review every generated patch and require explicit authorization before publishing a PR.
- **Full traceability**: record tasks, tool calls, retries, patches, tests, reviews, PRs, and CI events.
- **Three entry points**: use the same engine through the local CLI, generic REST API, or GitHub webhooks.

## Project status

`v0.1.0-mvp` is complete and has passed a real end-to-end validation:

- Python runtime: 295 unit tests passed.
- Java control plane: Maven test suite passed.
- Docker Compose: PostgreSQL, runtime, and control-plane health checks passed.
- GitHub cloud loop: Issue → Webhook → Agent → Patch → Test → Review → PR → CI → status writeback → `SUCCEEDED`.
- Webhook signature validation, delivery idempotency, run timeouts, submission retries, and concurrency limits have implementations or validation scripts.

> This is a complete MVP validated against a real GitHub workflow. It can serve as a personal auto-fix tool, a team code-change bot, or an agent execution platform embedded in another system.

## Three ways to use it

| Entry point | Best for | Result |
| --- | --- | --- |
| Local CLI | Personal development and quick fixes | Edits, test result, diff, optional branch/commit/PR |
| Generic REST API | Internal platforms and business systems | Async tasks, status, artifacts, callbacks, and audit records |
| GitHub mode | Team repository automation | Issue triggers, human approval, PR creation, and CI writeback |

## Quick start: local CLI

Python 3.10 or newer is required.

```bash
git clone https://github.com/ZhihaoTie/CodeAgentX.git
cd CodeAgentX
python -m pip install -e .
cp .env.example .env
```

Configure a model provider and API key using `.env.example`, then inspect the project:

```bash
codeagentx doctor
```

Save a verifier and run the normal fix loop:

```bash
codeagentx init --verify "pytest -q" --yes
codeagentx fix --yes
```

Or provide the verifier directly:

```bash
codeagentx fix --verify "pytest -q" --yes
```

If verification already passes, `fix` does not start an agent run. If it fails, CodeAgent-X extracts failing tests, relevant files, and stdout/stderr and gives that context to the agent.

### Create a branch, commit, and PR

```bash
codeagentx run "Fix the failing tests" \
  --verify "pytest -q" \
  --branch \
  --commit \
  --yes
```

Configure a GitHub token and add `--pr` to push the branch and open a pull request:

```bash
export CODEAGENTX_GITHUB_TOKEN="..."

codeagentx run "Fix the failing tests" \
  --verify "pytest -q" \
  --branch --commit --pr --yes
```

For interactive use, run `codeagentx chat`.

## Quick start: server platform

```text
GitHub / External System
          │
          ▼
┌──────────────────────────┐
│ Spring Boot Control Plane│  :8080
│ task / review / PR / CI  │
└─────────────┬────────────┘
              ▼
┌──────────────────────────┐
│ Python Agent Runtime     │  :8765 (Compose network only)
│ plan / tools / patch/test│
└─────────────┬────────────┘
        shared /workspaces
              │
┌─────────────▼────────────┐
│ PostgreSQL               │  (Compose network only)
└──────────────────────────┘
```

```bash
cp .env.example .env
docker compose up -d --build
curl http://127.0.0.1:8080/api/health
```

If the server has no public IP, expose the webhook through a reverse tunnel such as Cloudflare Tunnel:

```text
https://<your-domain>/api/webhooks/github
```

See the [deployment guide](docs/deployment.md) for the full topology and configuration.

## GitHub workflow

1. A GitHub Issue event is delivered to `/api/webhooks/github`.
2. The control plane persists a Task / Run and prepares an isolated workspace.
3. The Python runtime inspects the repository, edits files, and runs the verifier.
4. The patch and test report enter `NEEDS_REVIEW`.
5. `APPROVE` accepts the patch; `AUTHORIZE_PR` permits PR publication.
6. The control plane creates a branch and commit, pushes it, and opens a PR.
7. GitHub Actions runs CI, and `workflow_run` writes the result back to CodeAgent-X.
8. The Run enters `SUCCEEDED` when CI passes.

The two review actions are intentional: **accepting a code change** and **authorizing external PR publication** are separate permission boundaries.

## Architecture

### Python execution plane

`codeagentx/` handles repository operations: the agent loop, file and shell tools, AST/keyword retrieval, risk classification, workspace safety, patch transactions, verification, failure reflection, retries, trajectory reports, benchmarks, and SWE-bench adapters.

### Java control plane

`control-plane/` manages the platform workflow: Task / Run persistence, asynchronous scheduling, state transitions, event timelines, GitHub webhooks, human review, PR publication, generic REST integration, callbacks, health checks, and metrics.

## Common API endpoints

```text
POST /api/adapters/generic/tasks   Create a generic task
GET  /api/runs/{runId}             Read run status
POST /api/runs/{runId}/refresh     Synchronize runtime results
POST /api/runs/{runId}/review      Submit a review decision
GET  /api/runs/{runId}/audit       Read the full audit record
GET  /api/runs/summary             Read the run summary
GET  /api/health                   Health check
GET  /api/config/preflight         Configuration preflight
POST /api/webhooks/github          GitHub webhook endpoint
```

## Tests

```bash
# Python runtime
python -m unittest discover -s tests -v

# Control plane (JDK 17 + Maven)
cd control-plane && mvn test

# Deterministic three-minute demo
python demos/run_3min_demo.py
```

## Repository layout

```text
codeagentx/         Python agent runtime
control-plane/      Spring Boot control plane
tests/              Python unit tests
demos/              Local and deployment validation scripts
benchmarks/         Benchmark specs and fixtures
examples/           Example configuration and input
docs/               Architecture, deployment, and validation docs
```

## Scope

CodeAgent-X currently focuses on a reliable engineering loop for a single machine or server. Kubernetes, Kafka, distributed queues, multi-agent orchestration, IDE plugins, and a full administration dashboard are outside the MVP scope.

Use the local CLI for everyday coding assistance. Deploy the control plane when you need GitHub triggers, human approval, PR/CI writeback, and auditability.

## More documentation

- [Chinese documentation index](docs/README.md)
- [Project and architecture](docs/overview.md)
- [Deployment guide](docs/deployment.md)
- [GitHub workflow](docs/github-workflow.md)
- [Release checks](docs/release.md)
