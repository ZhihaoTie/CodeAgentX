# Docker Compose Deployment

This is the production-like single-node deployment path for CodeAgent-X. It is intentionally small: Docker Compose starts the control plane, the Python runtime, PostgreSQL, and a shared workspace volume. It does not introduce Kubernetes, a message queue, or an external observability stack.

## Topology

```text
Internet / local operator
        |
        v
Spring Boot control-plane :8080
        |
        | private Docker network
        v
Python runtime :8765
        |
        v
shared /workspaces volume
        |
        v
PostgreSQL persistent volume
```

Only the control-plane port is published by default. PostgreSQL and the Python runtime stay inside the Compose network.

## Quick start

```bash
cp .env.example .env
# edit .env and set real secrets only when needed
docker compose up -d --build
python demos/run_compose_smoke.py
```

The smoke script is read-only. It checks:

- `/api/health`
- `/api/config/preflight`
- `/api/metrics`
- `X-Request-Id` echo behavior

## Important environment choices

For local GitHub publishing, set these in `.env` or deployment secrets:

```text
CODEAGENTX_PUBLISHER_MODE=github
CODEAGENTX_GITHUB_TOKEN=...
CODEAGENTX_GITHUB_REPOSITORY=owner/repo
CODEAGENTX_GITHUB_BASE_BRANCH=main
CODEAGENTX_GITHUB_WEBHOOK_SECRET=...
```

For Docker/Linux deployments, verification commands should use `python`, not Windows `py -3.13`:

```text
CODEAGENTX_GITHUB_DEFAULT_VERIFICATION_COMMAND=python -m unittest discover -s tests -v
```

Generic REST callbacks are disabled by default:

```text
CODEAGENTX_CALLBACKS_ENABLED=false
```

Enable them only when the callback receiver is trusted and reachable from the control-plane container.

## Trust boundaries

The Python runtime can read and edit repositories and run verification commands. Treat it as an internal execution service, not a public API.

The first Compose deployment therefore keeps these boundaries:

- public: Spring Boot control-plane API on port `8080`
- private: Python runtime internal API on port `8765`
- private: PostgreSQL on port `5432`
- shared: `/workspaces` Docker volume between control-plane and runtime
- persisted: PostgreSQL data volume

Do not expose arbitrary task submission for untrusted repositories. Production-like runs should use a known repository, constrained verification commands, workspace boundaries, and least-privilege GitHub tokens.

## Operational validation checklist

After `docker compose up -d --build`, run:

```bash
docker compose ps
python demos/run_compose_smoke.py
```

Then verify the deployment behavior you care about:

1. Cold deployment: clone/copy repo, configure `.env`, build, start, smoke check.
2. Persistence: restart with `docker compose restart` and confirm tasks/runs remain in PostgreSQL.
3. Duplicate webhook: replay the same GitHub delivery id and confirm it maps to one task/run.
4. Timeout: run a deterministic timeout case and confirm the run fails cleanly.
5. Concurrency: lower worker limits and confirm extra tasks wait instead of running unbounded.
6. Generic adapter: submit through `/api/adapters/generic/tasks` and, if enabled, verify result callback delivery.
7. Real GitHub flow: Issue -> webhook -> task -> runtime -> review -> PR -> CI writeback.

## Shutdown

```bash
docker compose down
```

To remove persisted database/workspace volumes, use the destructive variant only when you intentionally want a clean slate:

```bash
docker compose down -v
```
