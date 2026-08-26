# CodeAgent-X 项目总结

## 一句话定位

CodeAgent-X 是一个软件工程 Agent Runtime 与工作流平台，它将代码任务转化为带测试证据、人工审核和完整审计记录的代码变更。

## 解决的问题

普通 Coding Agent 往往只关注“模型是否修改了文件”。CodeAgent-X 关注修改前后的工程边界：

- 任务从哪里进入系统；
- 仓库如何隔离和准备；
- Agent 可以使用哪些工具；
- 修改后如何执行验证；
- 失败后如何反思和重试；
- 人类如何审核补丁；
- 补丁如何成为 PR；
- CI 结果如何回写并形成审计记录。

## 系统组成

### Python 执行平面

`codeagentx/` 负责实际仓库工作：

- Agent Loop、计划和运行状态；
- 文件读取、编辑、搜索与 Shell 工具；
- AST 与文本上下文检索；
- 命令风险分类和工作区边界；
- 补丁事务与回滚元数据；
- 验证命令、测试结果解析、失败反思和重试；
- 轨迹报告、Benchmark 与 SWE-bench 适配。

### Java 控制平面

`control-plane/` 负责平台工作流：

- Task / Run 持久化与异步调度；
- 状态机、事件、时间线和审计 API；
- GitHub Issue 与 `workflow_run` Webhook；
- 人工审核与 PR 发布权限；
- 分支、提交、推送和 PR 创建；
- 通用 REST Adapter、结果回调、健康检查与指标。

## 三种使用入口

### 本地开发模式

适合个人在当前仓库快速修复：

```bash
codeagentx doctor
codeagentx init --verify "pytest -q" --yes
codeagentx fix --yes
```

### 通用集成模式

外部系统通过下面的接口创建任务：

```http
POST /api/adapters/generic/tasks
```

Control Plane 负责工作区、安全边界、异步执行、状态和回调。

### GitHub 平台模式

```text
Issue → Webhook → Agent → Patch → Test
      → Review → PR → CI → 状态回写
```

适合团队仓库自动化，同时保留人工审核与审计能力。

## 可靠性设计

- Webhook 幂等处理；
- 队列恢复与 Runtime 提交重试；
- 卡住任务超时；
- Worker 并发限制；
- Request ID 关联；
- 回调投递记录；
- 确定性验证报告；
- Patch Policy 与工具编辑回滚元数据。

## 最终状态

当前 MVP 已完成：

- Python Runtime 和本地 CLI；
- `doctor`、`init`、`fix`；
- Spring Boot Control Plane；
- Generic REST 和 GitHub Webhook；
- 人工审核、Git 分支/提交/推送和 PR 创建；
- GitHub Actions CI 状态回写；
- Docker Compose 单机部署；
- 健康、指标、配置预检、审计、事件和产物 API；
- 本地 Benchmark 与 SWE-bench 集成路径。

真实 GitHub 闭环已经到达最终 `SUCCEEDED`。项目当前应以稳定、易用和文档维护为主，不再扩张核心范围。

## 有意不做的内容

- Kubernetes 或大规模分布式编排；
- Redis、Kafka 等额外队列基础设施；
- 多 Agent 编排平台；
- IDE 插件或完整编辑器；
- 完整管理后台；
- 未经审核自动合并主分支。
