# CodeAgent-X MVP 最终验收记录

## 验收结论

**CodeAgent-X 当前阶段目标已经达成。**

三个入口均能使用同一套 Agent 执行能力：

| 入口 | 状态 | 主要证据 |
| --- | --- | --- |
| 本地 CLI | 通过 | `doctor`、`init`、`fix` 和本地 PR 参数有测试覆盖 |
| Generic REST | 通过 | 任务创建、Runtime、产物、状态与回调 Smoke 通过 |
| GitHub 平台 | 通过 | 真实 Issue → PR → Actions CI → `SUCCEEDED` 闭环完成 |

## 自动化测试

Python：

```text
python -m unittest discover -s tests -v
Ran 295 tests
OK
```

Control Plane：

```text
mvn test
所有测试通过
```

## 真实服务器 E2E

最终验证链路：

```text
GitHub Issue
 → GitHub Webhook
 → Task / Run
 → 仓库克隆与工作区准备
 → Runtime 分析和修改
 → 验证通过
 → NEEDS_REVIEW
 → APPROVE
 → AUTHORIZE_PR
 → 分支 / Commit / Push
 → Pull Request
 → GitHub Actions CI
 → workflow_run 回写
 → SUCCEEDED
```

目标仓库：`https://github.com/ZhihaoTie/CodeAgent`

验证补丁将 `normalize_title` 从小写转换修正为标题格式，目标仓库两项测试全部通过。最终 PR 和 CI 结果均在 GitHub 云端完成，并成功回写平台。

## 验收过程中修复的问题

1. Generic Task 请求字段应使用 `body`，而不是 `prompt`。
2. Control Plane 与 Runtime 的容器 UID 必须一致，并共享可写工作区。
3. Git 需要仅信任当前 Run 的 `safe.directory`。
4. Control Plane 容器需要配置提交者姓名和邮箱。
5. Git 推送需要通过非交互式 Token 凭据完成，Token 不能写入 Remote URL。
6. GitHub Webhook Secret 必须启用并校验签名。

这些问题已经在代码、Dockerfile、Compose 配置或部署 ACL 中处理。

## 环境问题说明

测试期间出现过 Docker Hub、Maven Central 和 Cloudflare Quick Tunnel 超时。这些问题来自服务器出口网络，并非业务逻辑缺陷。网络恢复后，完整 PR/CI 闭环已最终成功。

## 最终边界

可以公开陈述：

- Agent 能检查、修改并验证真实仓库；
- 本地 CLI、REST 和 GitHub 三种入口可用；
- 人工审核、PR 发布和 CI 回写闭环已验证；
- 单机 Docker Compose 部署已验证；
- 运行过程具有事件、产物和审计记录。

不应夸大为：

- 已完成大规模分布式生产部署；
- 可对任意不可信仓库开放执行；
- 已获得新的官方 SWE-bench 排名；
- 可以绕过人工审核自动合并主分支。

## 冻结建议

MVP 主线应冻结。后续工作以缺陷修复、易用性、安全、文档和发布维护为主。
