# 项目与架构

## 项目定位

CodeAgent-X 是一个软件工程 Agent Runtime 与工作流平台。它将代码任务转化为带测试证据、人工审核和审计记录的代码变更。

它不是 Cursor 或 Codex 的聊天界面替代品，而是在模型编辑代码之外补齐工程流程：任务进入、仓库隔离、工具权限、测试验证、失败重试、人工审核、PR 发布和 CI 状态回写。

## 完整工作流

```text
GitHub Issue / REST / Local CLI
             ↓
        Task / Run
             ↓
  Agent 分析 → 修改 → 验证 → 失败重试
             ↓
      补丁与测试报告
             ↓
  人工审核 → PR → CI → 状态回写
             ↓
         SUCCEEDED
```

## 两个执行平面

### Python Runtime

`codeagentx/` 负责仓库内的实际工作：

- Agent Loop、计划与运行状态；
- 文件、搜索、AST 和 Shell 工具；
- 命令风险分类与工作区安全；
- 补丁事务和回滚元数据；
- 验证命令、测试解析、失败反思与重试；
- 轨迹、Benchmark 和 SWE-bench 适配。

### Java Control Plane

`control-plane/` 负责平台流程：

- Task / Run 持久化与异步调度；
- 状态机、事件、时间线与审计 API；
- GitHub Issue 和 `workflow_run` Webhook；
- 人工审核与 PR 发布权限；
- 分支、提交、推送和 PR 创建；
- Generic REST、结果回调、健康检查与指标。

## 三种使用方式

| 模式 | 使用方式 | 适用场景 |
| --- | --- | --- |
| 本地开发 | `codeagentx doctor/init/fix/run/chat` | 个人仓库快速修复 |
| Generic REST | `POST /api/adapters/generic/tasks` | 接入内部平台或业务系统 |
| GitHub 平台 | Issue + Webhook + Review + PR/CI | 团队仓库自动化 |

## 可靠性与安全

- 工作区路径边界和命令风险分类；
- 补丁事务与编辑回滚元数据；
- Webhook 签名和重复投递幂等；
- Runtime 提交重试、任务超时和并发限制；
- Request ID、回调记录、事件时间线和审计产物；
- `APPROVE` 与 `AUTHORIZE_PR` 两级人工权限。

## MVP 完成情况

`v0.1.0-mvp` 已完成并验证：

- Python 295 项单元测试通过；
- Control Plane Maven 测试通过；
- Docker Compose 三服务健康；
- Local CLI、Generic REST 和 GitHub 三种入口可用；
- 真实 GitHub `Issue → PR → Actions CI → SUCCEEDED` 闭环成功。

验收过程中解决了共享工作区 UID/ACL、Git `safe.directory`、提交身份、非交互式 Token Push 和 Webhook Secret 等真实部署问题。

## 当前边界

项目当前以单机或单服务器的可靠闭环为目标。以下内容不属于 MVP：

- Kubernetes、Kafka 或大规模分布式编排；
- 多 Agent 平台；
- IDE 插件或完整编辑器；
- 完整管理后台；
- 对任意不可信仓库公开执行；
- 绕过审核自动合并主分支。

MVP 主线已经冻结，后续优先处理缺陷、易用性、安全、文档和发布维护。

