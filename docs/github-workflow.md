# GitHub 工作流与端到端验收

## 目标

```text
Issue → Webhook → Task / Run → Agent → Patch → Test
      → APPROVE → AUTHORIZE_PR → PR → CI → SUCCEEDED
```

建议使用独立测试仓库完成首次验收。已验证目标仓库：

```text
https://github.com/ZhihaoTie/CodeAgent
```

## 前置检查

- Compose 服务健康；
- Publisher Mode 为 `github`；
- Token 有读取、推送分支和创建 PR 权限；
- Webhook Secret 已配置；
- 目标仓库有 GitHub Actions Workflow；
- GitHub 能访问 `/api/webhooks/github`。

```bash
curl -sS http://127.0.0.1:8080/api/health
curl -sS http://127.0.0.1:8080/api/config/preflight
```

## 触发并检查任务

在目标仓库创建范围小、要求清晰且可测试的 Issue。Webhook 成功后查询：

```bash
curl -sS http://127.0.0.1:8080/api/runs/summary
RUN_ID="<run-id>"
curl -sS "http://127.0.0.1:8080/api/runs/$RUN_ID"
```

预期：

```text
CREATED → QUEUED → RUNNING → NEEDS_REVIEW
```

审核前确认 Diff、Changed Files 和 Test Report 符合预期，且不包含 `.codeagentx/` 私有目录。

## 两级审核

先认可补丁：

```bash
curl -sS -X POST "http://127.0.0.1:8080/api/runs/$RUN_ID/review" \
  -H 'Content-Type: application/json' \
  -d '{"decision":"APPROVE","comment":"Patch reviewed."}'
```

状态变为 `APPROVED` 后，授权发布 PR：

```bash
curl -sS -X POST "http://127.0.0.1:8080/api/runs/$RUN_ID/review" \
  -H 'Content-Type: application/json' \
  -d '{"decision":"AUTHORIZE_PR","comment":"Authorize PR publication."}'
```

注意：请求枚举值是 `APPROVE`，不是 `APPROVED`。不能跳过状态顺序。

## PR 与 CI

授权后预期：

```text
PR_CREATING
 → PATCH_BRANCH_PREPARED
 → PATCH_COMMITTED
 → PATCH_PUSHED
 → PR_CREATED
 → CI_RUNNING
 → SUCCEEDED
```

`workflow_run.head_branch` 必须与 Run 的 `patchBranch` 匹配，才能正确回写 CI。

## 最终审计

```bash
curl -sS "http://127.0.0.1:8080/api/runs/$RUN_ID/audit"
```

最终应具有 Patch、Verification、Review、PR 和 CI 记录，状态为 `SUCCEEDED`。

## 已验证结论

- 真实 GitHub Issue 成功触发任务；
- Agent 修复目标代码，2 项测试通过；
- 人工审核与 PR 授权生效；
- 分支、Commit、Token Push 和 PR 创建成功；
- GitHub Actions CI 成功；
- `workflow_run` 回写成功；
- 最终平台状态为 `SUCCEEDED`。

曾出现的 Docker Hub、Maven Central 和 Quick Tunnel 超时属于出口网络波动。网络恢复后完整闭环成功，没有剩余业务逻辑阻塞。

## 故障定位

1. 没有 Run：检查 GitHub Delivery、Tunnel 和 Webhook Secret。
2. Clone 失败：在 Control Plane 容器内测试 `git clone`。
3. Runtime 不能写：检查容器 `id`、工作区所有者和 ACL。
4. 长时间 `RUNNING`：查看 Runtime 日志并调用 `/refresh`。
5. Commit 失败：检查 Git Identity 与 `safe.directory`。
6. Push 失败：检查镜像版本、Token 权限和出口网络。
7. PR 后不结束：检查 `workflow_run` 订阅和 Head Branch 匹配。

