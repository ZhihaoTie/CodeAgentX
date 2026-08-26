# CodeAgent-X 2.0 规划与完成情况

> 本文是规划归档。功能现状以 [项目总结](project-summary.md) 和 [最终验收记录](final-validation.md) 为准。

## 目标

2.0 的目标是将独立的 Python Coding Agent 扩展为可接入真实开发流程的平台：

```text
任务进入 → 仓库准备 → Agent 执行 → 补丁与测试
        → 人工审核 → PR → CI 回写 → 审计归档
```

## 设计原则

1. Agent 负责代码推理，平台负责流程和权限。
2. 所有代码变更都必须产生可读 diff 和验证证据。
3. 审核补丁与授权发布 PR 是两个独立动作。
4. Runtime 不直接暴露公网，只允许 Control Plane 调用。
5. 外部系统不能任意指定服务器工作区。
6. 重复 Webhook、超时、重试和重启必须可预测。

## 原计划里程碑

| 阶段 | 目标 | 状态 |
| --- | --- | --- |
| V1 | Task / Run、Runtime 调用、补丁与测试报告 | 完成 |
| V2 | 人工审核、状态机、事件和审计 | 完成 |
| V3 | GitHub Issue、分支、提交、推送和 PR | 完成 |
| V4 | `workflow_run` CI 回写和最终状态 | 完成 |
| V5 | Compose 部署、可靠性和发布整理 | 完成 |

## 已验证主链路

```text
GitHub Issue
 → Webhook 签名验证与幂等处理
 → 持久化 Task / Run
 → 克隆仓库到独立工作区
 → Python Runtime 修改代码
 → 验证命令通过
 → NEEDS_REVIEW
 → APPROVE
 → AUTHORIZE_PR
 → 创建并推送补丁分支
 → 创建 Pull Request
 → GitHub Actions CI
 → workflow_run 回写
 → SUCCEEDED
```

## 范围冻结

2.0 MVP 已完成。后续只优先处理：

- 可重复出现的缺陷；
- 安装、配置和错误提示；
- 安全边界和测试覆盖；
- 文档、示例和发布维护。

Kubernetes、多 Agent、IDE 插件和管理后台应作为独立的新阶段评估，不能作为 2.0 收尾条件。
