# Clean Server Deployment Validation

This record captures a production-like single-node deployment validation on a clean Linux server. The deployment was intentionally kept under one removable project directory so it can be cleaned up without touching unrelated system paths.

## Scope

Validation date: 2026-08-25

Deployment root:

```text
/data/fast/zhihao/
```

Project layout:

```text
/data/fast/zhihao/
├── codeagentx-deploy/
├── codeagentx-data/
└── codeagentx-workspaces/
```

The operator constraint for this validation was: do not modify server content outside `/data/fast/zhihao`.

## Server toolchain

The server reported:

```text
Docker version 29.4.0
Docker Compose version v5.1.2
```

## Deployment commands

From:

```text
/data/fast/zhihao/codeagentx-deploy
```

The deployment path was:

```bash
cp .env.example .env
docker compose up -d --build
docker compose ps
python3 demos/run_compose_smoke.py
```

## Result

The Compose build completed successfully and started all three services:

- `codeagentx-postgres`
- `codeagentx-runtime`
- `codeagentx-control-plane`

The smoke script reported:

```json
{
  "preflightStatus": "ready",
  "missing": [],
  "warnings": []
}
```

The health response confirmed:

- database connectivity: `ok`
- Python runtime connectivity: `ok`
- runtime base URL: `http://runtime:8765`
- workspace root: `/workspaces`
- callback delivery disabled for the first smoke run

The metrics response confirmed:

- worker pool configuration was visible
- runtime configuration was visible
- publisher configuration was visible
- no runs were present before task submission

## Interpretation

This validates the clean-server deployment path:

```text
git clone / configure .env
        ↓
docker compose up -d --build
        ↓
PostgreSQL + Python runtime + Spring Boot control plane
        ↓
health / preflight / metrics smoke
```

At this point, CodeAgent-X has evidence for a production-like Docker Compose deployment on a Linux server, not only local Windows/IDE execution.

## Follow-up validations

Recommended follow-up checks:

1. Re-run Compose with explicit bind-mounted storage under `/data/fast/zhihao/codeagentx-data` and `/data/fast/zhihao/codeagentx-workspaces`.
2. Run callback delivery smoke with callbacks enabled.
3. Run restart recovery smoke.
4. Run a controlled generic task through the REST adapter.
5. Run the real GitHub Issue → task → review → PR path only after secrets are configured deliberately.
