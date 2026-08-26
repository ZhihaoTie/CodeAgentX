# 测试与发布检查

## 1. 仓库状态

```bash
git status --short --branch
git remote -v
git log --oneline -10
```

确认 Remote 正确、工作树符合预期、没有本地文件进入暂存区。

## 2. 私有文件与敏感信息

以下内容不能提交：

```text
.env
.codeagentx/
logs/
docs/local/
control-plane/target/
__pycache__/
.pytest_cache/
```

检查 Token、API Key、Webhook Secret、临时 Tunnel URL 和内部地址：

```bash
git status --short --ignored
rg -n -i "token|api[_-]?key|secret|trycloudflare" \
  --glob '!/.git/**' --glob '!/.codeagentx/**' .
```

变量名可以公开，真实值必须删除。

## 3. 自动化测试

```bash
# Python
python -m unittest discover -s tests -v

# Control Plane，要求 JDK 17
cd control-plane && mvn test
```

当前 Python 基线为 295 项测试通过。测试数量变化时同步更新 README 和 [项目与架构](overview.md)。

## 4. 文档与 Compose

```bash
git diff --check
docker compose up -d --build
python demos/run_compose_smoke.py
```

确认 Markdown 相对链接存在，命令与当前 CLI/API 一致，三个服务健康且工作区可写。

涉及 Webhook、Git、Publisher、审核或 CI 状态机时，还应复现：

```text
Issue → Patch → Test → APPROVE → AUTHORIZE_PR → PR → CI → SUCCEEDED
```

## 5. 审阅并发布

```bash
git diff --cached --stat
git diff --cached
git commit -m "Prepare release <version>"
git push origin main
git tag -a <version> -m "CodeAgent-X <version>"
git push origin <version>
```

已发布标签尽量不要移动或覆盖。纯文档修改可以推送 `main`，无需重写旧标签。

## 公开表述边界

可以陈述：Runtime、Control Plane、三种入口、测试验证、人工审核、PR/CI 回写、单机 Compose、超时/重试/幂等/并发和审计能力。

未经重新验证，不应声称新的官方 SWE-bench 分数、大规模分布式生产能力、任意不可信仓库安全执行，或无人审核自动合并主分支。
