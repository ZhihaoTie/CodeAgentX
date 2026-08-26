# CodeAgent-X Benchmark Suite

`benchmarks/` 保存我们用于验证 Agent 工程能力的固定任务和隔离夹具。这套 Benchmark 用于本地回归与消融实验，不代表官方 SWE-bench 成绩。

## Suite v0

`suite-v0.json` 包含 20 个故意处于失败状态的小型任务，覆盖 Python、JavaScript 和 TypeScript：

- 每个任务使用 `benchmarks/fixtures/` 下的独立工作区；
- 初始验证命令必须失败；
- Path Constraint 限制 Agent 修改实现文件，不能通过修改测试绕过任务；
- JavaScript 和 TypeScript 任务使用 Python 静态验证器，避免额外 Runtime 依赖；
- Suite 声明 Planner、Context Ranking、Reflection、Retry、Tool Guidance、Task Constraint 和 Patch Policy 等消融变量。

## 运行单个夹具

进入对应 Fixture 后执行它声明的验证命令，例如：

```bash
python -B -m unittest discover -s tests -v
```

## 运行完整 Suite

```bash
python -m codeagentx --benchmark benchmarks/suite-v0.json --mode auto
```

运行消融实验：

```bash
python -m codeagentx \
  --benchmark benchmarks/suite-v0.json \
  --benchmark-ablation \
  --mode auto
```

## 结果边界

这套任务用于观察修复成功率、工具调用、Token、错误、路径约束和验证驱动修复等行为。公开材料不能把本地 Suite 结果描述为官方 SWE-bench Resolved Score。
