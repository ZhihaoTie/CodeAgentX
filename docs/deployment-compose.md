# Docker Compose Deployment

This is the production-like single-node deployment path for CodeAgent-X. It is intentionally small: Docker Compose starts the control plane, the Python runtime, PostgreSQL, and a shared workspace volume. It does not introduce Kubernetes, a message queue, or an external observability stack. The current local validation record is maintained in [deployment-validation.md](deployment-validation.md).

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

## Clean server layout

For a disposable clean-server validation, keep every project-owned file under one removable directory:

```text
/data/fast/zhihao/
|-- codeagentx-deploy/      # git clone and docker-compose.yml
|-- codeagentx-data/        # PostgreSQL data when configured as a bind mount
`-- codeagentx-workspaces/  # cloned target repositories and runtime workspaces
```

Clone the repository into `codeagentx-deploy`, then set these values in `codeagentx-deploy/.env`:

```text
CODEAGENTX_POSTGRES_DATA_VOLUME=/data/fast/zhihao/codeagentx-data/postgres
CODEAGENTX_WORKSPACES_VOLUME=/data/fast/zhihao/codeagentx-workspaces
```

The default values still use Docker named volumes for local development. Absolute paths are recommended for a clean server when you want project data to be easy to inspect and remove.

On Linux, the control-plane service also maps `host.docker.internal` to Docker's host gateway. This lets callback smoke tests post from the container back to a callback receiver running on the server host.

The control-plane and runtime containers both run as the same `codeagentx` UID/GID (`1000:1000`) so a shared `/workspaces` bind mount can be used for clone, edit, test, patch branch, commit, and push operations. On a clean server, initialize the bind-mounted workspace path with:

```bash
sudo chown -R 1000:1000 /data/fast/zhihao/codeagentx-workspaces
sudo chmod -R u+rwX,g+rwX /data/fast/zhihao/codeagentx-workspaces
```

The control plane also marks each prepared workspace as a Git `safe.directory` before local branch, commit, and push operations. This avoids Git's dubious-ownership protection blocking review-authorized PR publication while still trusting only the current run workspace instead of using a global wildcard.

## Local prebuilt override

When Docker Hub or Maven builder layers are slow on a development machine, you can validate the same three-service runtime shape with a locally built control-plane jar:

```bash
cd control-plane
./mvnw -q -DskipTests package
cd ..
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build
python demos/run_compose_smoke.py
```

This override is for local validation only. The main `docker-compose.yml` remains the clean-machine path.

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
2. Restart recovery: run `python demos/run_compose_restart_smoke.py` and confirm health, preflight, metrics, and request-id behavior survive a Compose restart.
3. Persistence: create a controlled task/run and confirm it remains in PostgreSQL after restart.
4. Duplicate webhook: replay the same GitHub delivery id and confirm it maps to one task/run.
5. Timeout: run a deterministic timeout case and confirm the run fails cleanly.
6. Concurrency: lower worker limits and confirm extra tasks wait instead of running unbounded.
7. Generic adapter: run `python demos/run_compose_generic_callback_smoke.py` with callbacks enabled to verify external task intake, mock runtime execution, and result callback delivery.
8. Real GitHub flow: Issue -> webhook -> task -> runtime -> review -> PR -> CI writeback.

## Shutdown

```bash
docker compose down
```

To remove persisted database/workspace volumes, use the destructive variant only when you intentionally want a clean slate:

```bash
docker compose down -v
```
