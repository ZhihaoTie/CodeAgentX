# 公开发布检查清单

每次发布 CodeAgent-X 或推送正式版本前，按顺序执行本清单。

## 1. 确认 Git 状态

```bash
git status --short --branch
git remote -v
git log --oneline -10
```

确认：

- Remote 指向预期公开仓库；
- 没有意外源代码改动；
- 没有敏感文件进入暂存区；
- 当前分支与远端状态符合预期。

## 2. 检查本地私有文件

以下路径必须保持忽略：

```text
.env
.codeagentx/
logs/
docs/reports/
control-plane/target/
__pycache__/
.pytest_cache/
```

验证：

```bash
git status --short --ignored
git check-ignore -v .env .codeagentx
```

`.codeagentx/` 可能包含 Prompt、运行轨迹、目标仓库内容和模型输出，不应公开。

## 3. 检查敏感信息

重点搜索：

- GitHub Token、模型 API Key；
- Webhook Secret；
- 私有域名、IP 和用户名；
- 临时 Tunnel URL；
- 不应公开的运行日志。

示例：

```bash
rg -n -i "token|api[_-]?key|secret|trycloudflare" \
  --glob '!/.git/**' \
  --glob '!/.codeagentx/**' \
  --glob '!control-plane/target/**' .
```

搜索结果需要人工判断，配置变量名可以保留，真实值必须删除。

## 4. Python 测试

```bash
python -m unittest discover -s tests -v
```

当前基线：

```text
Ran 295 tests
OK
```

如果测试数量变化，应同步更新 README 和最终验收记录。

## 5. Control Plane 测试

要求 JDK 17：

```bash
cd control-plane
mvn test
```

必须为零 Failure 和零 Error。

## 6. 文档检查

```bash
git diff --check
```

确认：

- 中文和英文 README 可以互相切换；
- 文档相对链接存在；
- 命令与当前 CLI/API 一致；
- 不再出现已经失效的“PR/CI 尚未完成”结论；
- 不声称未实际验证的 Benchmark 成绩或生产规模。

## 7. Compose 验证

```bash
docker compose up -d --build
python demos/run_compose_smoke.py
```

至少确认：

```text
control-plane healthy
runtime healthy
database healthy
workspace writable
```

涉及部署代码变化时，还应运行重启、回调、超时或并发相关 Smoke。

## 8. GitHub E2E

涉及 Webhook、Git、Publisher、审核或 CI 状态机变化时，使用独立测试仓库复现：

```text
Issue → Patch → Test → APPROVE → AUTHORIZE_PR
      → PR → CI → SUCCEEDED
```

不要在包含真实业务代码的仓库上进行首次验证。

## 9. 检查提交内容

```bash
git diff --cached --stat
git diff --cached
```

确认没有：

- `.env` 或凭据；
- Runtime 私有目录；
- Target Repository 工作区；
- 大型日志和构建产物；
- 与本次发布无关的修改。

## 10. 提交、推送和标签

```bash
git commit -m "Prepare release <version>"
git push origin main
git tag -a <version> -m "CodeAgent-X <version>"
git push origin <version>
```

标签发布后尽量不要移动或覆盖。若只修改文档，可以提交到 `main`，不必重写已有版本标签。

## 可公开陈述的范围

- 软件工程 Agent Runtime；
- Python 执行平面与 Spring Boot 控制平面；
- 本地 CLI、Generic REST、GitHub Webhook；
- 测试验证、人工审核、PR 与 CI 回写；
- 单机 Docker Compose 部署；
- 超时、重试、幂等、并发限制和审计；
- Benchmark 工具与 SWE-bench 集成路径。

除非重新验证并保存证据，否则不要声称：

- 新的官方 SWE-bench 分数；
- 大规模分布式生产能力；
- 对任意不可信仓库安全开放；
- 无人审核自动合并到主分支。
