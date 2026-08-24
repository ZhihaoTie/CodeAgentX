# CodeAgent-X Benchmark Suite

This directory contains fixed benchmark fixtures for evaluating CodeAgent-X on small, reproducible software-engineering tasks.

## Suite v0

`suite-v0.json` is the first stable suite. It is intentionally compact and local-only:

- each task has an isolated fixture workspace under `benchmarks/fixtures/`;
- the suite currently contains 20 failing-by-design tasks across Python, JavaScript, and TypeScript;
- each fixture starts with a failing verification command;
- tasks include path constraints so the agent must fix implementation files instead of editing tests or notes;
- JavaScript and TypeScript tasks use Python static validators to avoid external runtime dependencies;
- the same suite declares ablation variants for runtime planning, context ranking, reflection, retry strategy, tool guidance, task constraints, and patch policy.

Run one task manually from its fixture directory:

```bash
python -B -m unittest discover -s tests -v
```

Run the suite through CodeAgent-X:

```bash
python -m codeagentx --benchmark benchmarks/suite-v0.json --mode auto
python -m codeagentx --benchmark benchmarks/suite-v0.json --benchmark-ablation --mode auto
```

The suite is designed to measure practical agent abilities rather than raw prompt compliance: focused debugging, multi-file reasoning, path-constraint adherence, and verification-driven repair.
