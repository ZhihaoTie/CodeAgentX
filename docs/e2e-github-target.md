# GitHub 端到端验收指南

本文用于复现 CodeAgent-X 的完整云端闭环。

## 验收目标

```text
Issue → Webhook → Task / Run → Agent 修改 → 测试
      → APPROVE → AUTHORIZE_PR → PR → CI → SUCCEEDED
```

测试目标仓库与 CodeAgent-X 平台仓库应分开。已验证的目标仓库是：

```text
https://github.com/ZhihaoTie/CodeAgent
```

## 前置条件

- Compose 服务健康；
- GitHub Publisher 为 `github`；
- Token 具有读取仓库、推送分支和创建 PR 的权限；
- Webhook Secret 已配置；
- 目标仓库存在 CI Workflow；
- GitHub 能访问 `/api/webhooks/github`。

先检查：

```bash
curl -sS http://127.0.0.1:8080/api/health
curl -sS http://127.0.0.1:8080/api/config/preflight
```

## 第一步：触发任务

在目标仓库创建一个描述明确、范围小且可测试的 Issue，例如：

```text
Title: Fix title normalization
Body: Make normalize_title trim whitespace and return title case. Run the existing tests.
```

GitHub Webhook 成功后查询：

```bash
curl -sS http://127.0.0.1:8080/api/runs/summary
```

记录最新的 `runId`。

## 第二步：等待 Agent 完成

```bash
RUN_ID="<run-id>"
curl -sS "http://127.0.0.1:8080/api/runs/$RUN_ID"
```

状态应依次经过：

```text
CREATED → QUEUED → RUNNING → NEEDS_REVIEW
```

检查以下内容：

- `patchArtifact.diffText` 只包含预期修改；
- `testReport.status` 为 `passed`；
- `changedFiles` 不包含 `.codeagentx/`；
- `failureReason` 为空。

## 第三步：审核补丁

先认可补丁：

```bash
curl -sS -X POST "http://127.0.0.1:8080/api/runs/$RUN_ID/review" \
  -H 'Content-Type: application/json' \
  -d '{
    "decision": "APPROVE",
    "comment": "Patch and verification reviewed."
  }'
```

状态应变为 `APPROVED`。注意枚举值是 `APPROVE`，不是 `APPROVED`。

然后授权创建 PR：

```bash
curl -sS -X POST "http://127.0.0.1:8080/api/runs/$RUN_ID/review" \
  -H 'Content-Type: application/json' \
  -d '{
    "decision": "AUTHORIZE_PR",
    "comment": "Authorize PR publication."
  }'
```

不能跳过顺序：`APPROVE` 仅允许在 `NEEDS_REVIEW` 执行，`AUTHORIZE_PR` 仅允许在 `APPROVED` 执行。

## 第四步：PR 与 CI

授权后应出现：

```text
PR_CREATING
 → PATCH_BRANCH_PREPARED
 → PATCH_COMMITTED
 → PATCH_PUSHED
 → PR_CREATED
 → CI_RUNNING
 → SUCCEEDED
```

GitHub Actions 的 `workflow_run.head_branch` 必须与 Run 的 `patchBranch` 匹配，Control Plane 才能关联 CI。

## 第五步：审计

```bash
curl -sS "http://127.0.0.1:8080/api/runs/$RUN_ID/audit"
```

最终应满足：

```text
hasPatch    = true
hasVerification = true
hasReview   = true
hasPr       = true
hasCi       = true
status      = SUCCEEDED
```

## 已验证结果

```text
目标仓库：https://github.com/ZhihaoTie/CodeAgent
补丁分支：codeagentx/run-<runId>
验证命令：python -m unittest discover -s tests -v
PR：成功创建
GitHub Actions：成功
CI 回写：成功
最终平台状态：SUCCEEDED
```

## 故障定位顺序

1. Webhook 没有 Run：检查 GitHub Delivery、Tunnel 和 Secret。
2. Clone 失败：在 Control Plane 容器内手动测试 `git clone`。
3. Runtime 不能写：对比两个容器的 `id` 和工作区 ACL。
4. 长时间 `RUNNING`：查看 Runtime 日志并调用 `/refresh`。
5. Commit 失败：检查 Git Identity 与 `safe.directory`。
6. Push 失败：检查部署镜像版本、Token 权限和出口网络。
7. PR 后不结束：确认订阅 `workflow_run` 且 Head Branch 匹配。

