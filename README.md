# CodeAgent-X

中文 | [English](README.en.md)

**把一个软件任务，可靠地变成可验证、可审核、可追踪的代码变更。**

我们开发 CodeAgent-X，是为了给真实仓库提供一套可控的软件工程 Agent Runtime 与工作流平台。它不仅让模型读写代码，还把任务执行、测试验证、失败重试、人工审核、Pull Request 和 CI 状态组织成一条完整闭环。

我们不把 CodeAgent-X 定位成另一个聊天界面，也不试图替代 Cursor 或 Codex。个人开发者可以使用轻量的本地 CLI；需要 GitHub 自动化、人工审批、审计记录和异步执行时，可以部署服务器端控制平面。

```text
GitHub Issue
    ↓
Webhook → Task / Run → Agent 修改代码 → 自动测试
    ↓
补丁与审计记录 → 人工审核 → Pull Request → GitHub Actions CI
    ↓
                       CI 结果回写 → SUCCEEDED
```

## 为什么使用 CodeAgent-X

- **从失败出发**：直接读取失败的测试或验证命令，不需要重新描述已知错误。
- **验证优先**：修改后执行同一条验证命令，并保存结构化测试结果。
- **安全修改**：限制工作区边界，记录补丁事务，保留回滚与审计信息。
- **人工把关**：补丁先进入审核，只有明确授权才创建 PR。
- **完整追踪**：任务、工具调用、重试、补丁、测试、审核、PR 和 CI 都有事件记录。
- **三种入口**：同一套能力可通过本地 CLI、通用 REST API 或 GitHub Webhook 使用。

## 当前状态

`v0.1.0-mvp` 已完成并通过真实端到端验证：

- Python Runtime：295 项单元测试通过。
- Java Control Plane：Maven 测试通过。
- Docker Compose：PostgreSQL、Runtime 与 Control Plane 健康检查通过。
- GitHub 云端闭环：Issue → Webhook → Agent → Patch → Test → Review → PR → CI → 状态回写 → `SUCCEEDED`。
- Webhook 签名校验、重复投递幂等、运行超时、提交重试和并发限制均有实现或验证脚本。

> 当前版本是一个经过真实 GitHub E2E 验证的完整 MVP，可作为个人自动修复工具、团队代码变更机器人，或嵌入其他系统的 Agent 执行平台。

## 三种使用方式

| 入口 | 适合场景 | 结果 |
| --- | --- | --- |
| 本地 CLI | 个人开发、当前仓库快速修复 | 修改、测试结果、diff，可选分支/提交/PR |
| 通用 REST API | 接入内部平台或业务系统 | 异步任务、状态、产物、回调与审计记录 |
| GitHub 模式 | 团队仓库自动化 | Issue 触发、人工审批、PR 创建与 CI 回写 |

## 快速开始：本地 CLI

要求 Python 3.10 或更高版本。

```bash
git clone https://github.com/ZhihaoTie/CodeAgentX.git
cd CodeAgentX
python -m pip install -e .
cp .env.example .env
```

按照 `.env.example` 配置模型 Provider 和 API Key，然后检查项目：

```bash
codeagentx doctor
```

保存项目验证命令，之后只需运行 `fix`：

```bash
codeagentx init --verify "pytest -q" --yes
codeagentx fix --yes
```

也可以直接指定验证命令：

```bash
codeagentx fix --verify "pytest -q" --yes
```

如果验证已经通过，`fix` 不会启动 Agent；如果失败，它会提取失败测试、相关文件和 stdout/stderr，作为修复上下文交给 Agent。

### 创建分支、提交和 PR

```bash
codeagentx run "Fix the failing tests" \
  --verify "pytest -q" \
  --branch \
  --commit \
  --yes
```

配置 GitHub Token 后可增加 `--pr`，自动推送分支并创建 PR：

```bash
export CODEAGENTX_GITHUB_TOKEN="..."

codeagentx run "Fix the failing tests" \
  --verify "pytest -q" \
  --branch --commit --pr --yes
```

交互使用：`codeagentx chat`。

## 快速开始：服务器平台

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
│ Python Agent Runtime     │  :8765（Compose 内部）
│ plan / tools / patch/test│
└─────────────┬────────────┘
        shared /workspaces
              │
┌─────────────▼────────────┐
│ PostgreSQL               │  （Compose 内部）
└──────────────────────────┘
```

```bash
cp .env.example .env
docker compose up -d --build
curl http://127.0.0.1:8080/api/health
```

服务器没有公网 IP 时，可以通过 Cloudflare Tunnel 等反向隧道暴露 Webhook：

```text
https://<your-domain>/api/webhooks/github
```

完整拓扑和配置见 [部署指南](docs/deployment.md)。

## GitHub 工作流

1. GitHub Issue 事件发送到 `/api/webhooks/github`。
2. Control Plane 创建 Task / Run，并准备独立工作区。
3. Python Runtime 分析仓库、修改文件并运行验证命令。
4. 补丁与测试报告进入 `NEEDS_REVIEW`。
5. `APPROVE` 确认补丁，`AUTHORIZE_PR` 授权发布 PR。
6. Control Plane 创建分支和提交，推送并调用 GitHub API 创建 PR。
7. GitHub Actions 执行 CI，`workflow_run` 将结果回写 CodeAgent-X。
8. CI 成功后 Run 进入 `SUCCEEDED`。

双重审核是有意设计的：**认可代码变更**与**允许对外发布 PR**是两个不同的权限边界。

## 核心架构

### Python 执行平面

`codeagentx/` 负责仓库操作：Agent Loop、文件与 Shell 工具、AST/关键词检索、风险分类、工作区安全、补丁事务、验证、失败反思、重试、轨迹记录、Benchmark 和 SWE-bench 适配。

### Java 控制平面

`control-plane/` 负责平台工作流：Task / Run 持久化、异步调度、状态机、事件时间线、GitHub Webhook、人工审核、PR 发布、通用 REST Adapter、回调、健康检查和指标。

## 常用 API

```text
POST /api/adapters/generic/tasks   创建通用任务
GET  /api/runs/{runId}             查询运行状态
POST /api/runs/{runId}/refresh     同步 Runtime 结果
POST /api/runs/{runId}/review      提交审核决定
GET  /api/runs/{runId}/audit       获取完整审计信息
GET  /api/runs/summary             查看运行汇总
GET  /api/health                   健康检查
GET  /api/config/preflight         配置预检
POST /api/webhooks/github          GitHub Webhook 入口
```

## 测试

```bash
# Python Runtime
python -m unittest discover -s tests -v

# Control Plane（JDK 17 + Maven）
cd control-plane && mvn test

# 确定性三分钟演示
python demos/run_3min_demo.py
```

## 仓库结构

```text
codeagentx/         Python Agent Runtime
control-plane/      Spring Boot Control Plane
tests/              Python 单元测试
demos/              本地与部署验收脚本
benchmarks/         Benchmark 配置与夹具
examples/           示例配置和输入
docs/               架构、部署与验收文档
```

## 项目边界

CodeAgent-X 当前关注单机或单服务器上的可靠工程闭环。Kubernetes、Kafka、分布式队列、多 Agent 编排、IDE 插件和完整管理后台不属于 MVP 范围。

只需要日常辅助编码时，本地 CLI 是最轻入口；需要 GitHub 自动触发、人工审批、PR/CI 回写和审计能力时，再部署 Control Plane。

## 更多文档

- [中文文档中心](docs/README.md)
- [项目与架构](docs/overview.md)
- [部署指南](docs/deployment.md)
- [GitHub 工作流](docs/github-workflow.md)
- [发布检查](docs/release.md)
