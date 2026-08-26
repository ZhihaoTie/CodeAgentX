# CodeAgent-X 文档中心

这里集中存放 CodeAgent-X 的公开说明、部署指南和验收记录。第一次了解项目，建议按下面顺序阅读。

## 推荐阅读顺序

1. [项目总结](project-summary.md)：先理解项目解决什么问题、由哪些部分组成。
2. [Docker Compose 部署](deployment-compose.md)：在单机或服务器上启动完整平台。
3. [GitHub 端到端流程](e2e-github-target.md)：配置 Issue、Webhook、人工审核、PR 和 CI 回写。
4. [最终验收记录](final-validation.md)：查看已经实际验证的能力与结果。
5. [公开发布检查清单](public-release-checklist.md)：提交代码或发布版本前执行。

## 文档分类

| 文档 | 类型 | 用途 |
| --- | --- | --- |
| [project-summary.md](project-summary.md) | 项目说明 | 定位、架构、入口和能力边界 |
| [codeagentx-2.0-plan.md](codeagentx-2.0-plan.md) | 规划归档 | 2.0 目标、完成情况和后续原则 |
| [deployment-compose.md](deployment-compose.md) | 操作指南 | Compose 拓扑、配置、启动和维护 |
| [e2e-github-target.md](e2e-github-target.md) | 操作指南 | 真实 GitHub PR/CI 闭环 |
| [deployment-validation.md](deployment-validation.md) | 验收记录 | 本地 Compose 能力验证 |
| [clean-server-deployment-validation.md](clean-server-deployment-validation.md) | 验收记录 | 干净 Linux 服务器部署验证 |
| [final-validation.md](final-validation.md) | 验收记录 | MVP 最终结论和证据 |
| [public-release-checklist.md](public-release-checklist.md) | 检查清单 | 测试、敏感信息和发布前检查 |

## 历史与本地材料

- `legacy/` 保存早期 MiniClaudeCode 资料，不代表当前架构。
- `reports/`、面试材料、路线草稿和本地评测输出由 `.gitignore` 排除，仅用于本地复盘。
- 项目的最新使用入口以根目录 [README](../README.md) 为准。

