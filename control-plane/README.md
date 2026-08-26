# CodeAgent-X Control Plane

Control Plane 是 CodeAgent-X 的平台控制层。我们使用 Spring Boot 实现任务持久化、异步调度、状态机、人工审核、GitHub Webhook、PR 发布和 CI 状态回写；实际仓库分析、编辑和验证由 Python Runtime 完成。

完整项目说明见：

- [项目与架构](../docs/overview.md)
- [部署指南](../docs/deployment.md)
- [GitHub 工作流](../docs/github-workflow.md)

## 环境要求

- JDK 17
- Maven
- PostgreSQL（默认 Profile）
- 运行中的 Python Runtime

## 本地启动

先在项目根目录启动 Runtime：

```powershell
py -3.13 -B -m codeagentx.service --host 127.0.0.1 --port 8765
```

再启动 Control Plane：

```powershell
cd control-plane
mvn spring-boot:run
```

不依赖 PostgreSQL 的本地 Smoke Profile：

```powershell
mvn spring-boot:run "-Dspring-boot.run.profiles=smoke"
```

## 检查服务

```bash
curl http://127.0.0.1:8080/api/health
curl http://127.0.0.1:8080/api/config/preflight
curl http://127.0.0.1:8080/api/runs/summary
```

- `/api/health`：数据库、Runtime、Publisher、Workspace 和 Webhook 签名状态。
- `/api/config/preflight`：GitHub Token、仓库、分支、Remote、Secret 和 Callback 配置。
- `/api/runs/summary`：运行总数、状态分布和最近 Run。

接口不会回显 Secret 的真实值。

## 核心工作流

```text
Task Intake
 → 持久化 Task / Run
 → WorkspacePreparer
 → 异步提交 Python Runtime
 → 轮询并收集 Patch / Test Report
 → NEEDS_REVIEW
 → APPROVE
 → AUTHORIZE_PR
 → Branch / Commit / Push / Pull Request
 → workflow_run CI 回写
 → SUCCEEDED / FAILED
```

`APPROVE` 用于认可补丁，`AUTHORIZE_PR` 用于授权对外发布 PR。我们将这两个动作设计为独立权限边界。

## 工作区

任务可以提供仓库元数据，由 Control Plane 克隆到受管工作区；服务器端工作区路径不能由不可信外部请求任意控制。

```text
repositoryUrl → Clone 到受管 Workspace → Checkout baseBranch
准备失败      → Run 在提交 Runtime 前进入 FAILED
```

Control Plane 会记录 `executionWorkspaceRoot`，并仅将当前 Run 工作区加入 Git `safe.directory`。Compose 部署中，Control Plane 与 Runtime 必须使用一致 UID/GID 并共享可写 `/workspaces`。

## GitHub Publisher

```text
CODEAGENTX_PUBLISHER_MODE=github
CODEAGENTX_GITHUB_TOKEN=...
CODEAGENTX_GITHUB_REPOSITORY=owner/repo
CODEAGENTX_GITHUB_BASE_BRANCH=main
CODEAGENTX_GITHUB_REMOTE_NAME=origin
CODEAGENTX_GITHUB_WEBHOOK_SECRET=...
```

授权后我们依次执行：

```text
创建 codeagentx/run-{runId} 分支
 → 暂存业务变更
 → 创建 CodeAgent-X run {runId} 提交
 → 使用非交互式 Token 凭据推送
 → 调用 GitHub API 创建 PR
```

Token 不会写入 Git Remote URL。目标仓库和 Base Branch 优先使用 Task 级配置，未提供时再使用全局环境变量。

## Webhook

统一入口：

```text
POST /api/webhooks/github
```

支持：

- `issues`：创建任务，使用 `X-GitHub-Delivery` 保证幂等；
- `workflow_run`：根据 `head_branch == patchBranch` 回写 CI；
- `X-Hub-Signature-256`：配置 Secret 后强制校验签名。

CI 状态映射：

```text
未完成             → CI_RUNNING
completed + success → SUCCEEDED
completed + 其他    → FAILED
```

## 可靠性

- 有界 Worker Pool 和队列；
- Runtime 提交重试；
- 定时轮询 Runtime；
- Run 超时；
- 启动时恢复 `QUEUED` Run；
- Webhook 与 Task 幂等；
- Callback 投递记录；
- Request ID；
- 持久化事件、审核、产物和审计时间线。

## 常用 API

```text
POST /api/tasks
POST /api/adapters/generic/tasks
POST /api/webhooks/github
GET  /api/runs/{runId}
POST /api/runs/{runId}/refresh
POST /api/runs/{runId}/review
POST /api/runs/{runId}/cancel
GET  /api/runs/{runId}/events
GET  /api/runs/{runId}/timeline
GET  /api/runs/{runId}/artifact
GET  /api/runs/{runId}/audit
GET  /api/runs/summary
GET  /api/health
GET  /api/config/preflight
GET  /api/metrics
```

## 测试

测试使用 H2，不要求本地 PostgreSQL：

```bash
cd control-plane
mvn test
```

完整 Compose 和 GitHub 验收命令见项目 [部署指南](../docs/deployment.md) 与 [GitHub 工作流](../docs/github-workflow.md)。
