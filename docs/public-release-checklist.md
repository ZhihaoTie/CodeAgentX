# Public Release Checklist

Use this checklist before publishing or pushing CodeAgent-X to a public repository.

## 1. Repository hygiene

Run from the repository root:

```bash
git status --short
```

Expected result before release:

```text
no unexpected uncommitted source changes
no local secret files staged
no generated private run artifacts staged
```

Private or local-only paths must stay out of public commits:

```text
.codeagentx/
.env
control-plane/target/
__pycache__/
.pytest_cache/
```

`.codeagentx/` may contain private trajectories, local benchmark artifacts, and internal notes. It is intentionally ignored and should not be uploaded.

## 2. Secret and private-wording scan

Run a public-surface scan excluding private and build-output paths:

```bash
rg -n -i "<private-career-wording>|<token-prefix>" \
  --glob '!/.git/**' \
  --glob '!/.codeagentx/**' \
  --glob '!control-plane/target/**' \
  --glob '!**/__pycache__/**' \
  .
```

The actual local scan should include the private wording and token prefixes that must not appear in public materials. Do not place real secrets in the command history if your shell history is synced or shared.

Expected result:

```text
no matches
```

Also inspect staged changes before pushing:

```bash
git diff --cached --stat
git diff --cached
```

## 3. Python runtime validation

Run:

```bash
py -3.13 -B -m unittest discover -s tests -v
```

Expected result:

```text
all tests pass
```

The public README should describe the latest verified local test count only after this command has been rerun on the current source tree.

## 4. Control-plane validation

Run:

```bash
cd control-plane
.\mvnw.cmd -q test
```

Expected result:

```text
all Maven tests pass on JDK 17
```

Current validated count:

```text
62 tests, 0 failures, 0 errors, 0 skipped
```

## 5. Compose deployment validation

Build or rebuild the local deployment:

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build
```

Then run:

```bash
py -3.13 -B demos\run_compose_smoke.py
py -3.13 -B demos\run_compose_restart_smoke.py --skip-restart
```

For callback-enabled Generic REST validation:

```bash
$env:CODEAGENTX_CALLBACKS_ENABLED="true"
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build
py -3.13 -B demos\run_compose_generic_callback_smoke.py
```

Expected result:

```text
control-plane healthy
runtime healthy
database healthy
preflight ready or needs_configuration, depending on local secrets
Generic REST task reaches NEEDS_REVIEW with callback delivery when callbacks are enabled
```

Clean server validation is tracked separately in:

```text
docs/clean-server-deployment-validation.md
```

For disposable Linux validation, keep deploy files, PostgreSQL data, and runtime workspaces under one removable root such as `/data/fast/zhihao`.

## 6. Claim discipline

Public materials may claim:

```text
software engineering Agent runtime
Spring Boot control plane
Python execution plane
asynchronous Task/Run workflow
PostgreSQL persistence
Docker Compose deployment path
Generic REST and GitHub task intake boundaries
review-gated PR publishing boundary
CI status writeback boundary
health, preflight, metrics, request correlation
failure recovery, timeout, retry, idempotency, and concurrency smokes
local benchmark/ablation harness
SWE-bench evaluator integration
```

Public materials should not claim unless freshly rerun and documented:

```text
new public benchmark leaderboard score
new official SWE-bench resolved score
large-scale distributed production deployment
fully autonomous merge to main
unrestricted execution on arbitrary untrusted repositories
```

## 7. Final pre-push commands

Run:

```bash
git log --oneline -10
git status --short
git remote -v
```

Only push after confirming:

```text
remote points to the intended public platform repository
working tree is clean
private paths remain ignored
validation commands above are current
README and docs describe only verified behavior
```

If a GitHub token is configured locally, keep it in `.env` or the platform secret store only. Never commit it, echo it, or paste it into public logs.
