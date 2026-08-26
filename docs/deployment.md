# 部署指南

## 拓扑

```text
GitHub / 外部调用方
        │ HTTP / Webhook
        ▼
Control Plane :8080 ─────► Runtime :8765
        │                    │
        ▼              shared /workspaces
PostgreSQL :5432
```

我们默认只把 Control Plane 暴露到宿主机；Runtime 和 PostgreSQL 留在 Compose 私有网络。

## 快速启动

```bash
git clone https://github.com/ZhihaoTie/CodeAgentX.git codeagentx-deploy
cd codeagentx-deploy
cp .env.example .env
# 编辑 .env
docker compose up -d --build
docker compose ps
curl -sS http://127.0.0.1:8080/api/health
```

健康响应应显示 Control Plane、Runtime 和 Database 均为 `ok`。

## 推荐服务器目录

```text
/data/codeagentx/
├── deploy/
├── postgres/
└── workspaces/
```

`.env`：

```text
CODEAGENTX_POSTGRES_DATA_VOLUME=/data/codeagentx/postgres
CODEAGENTX_WORKSPACES_VOLUME=/data/codeagentx/workspaces
```

## 共享工作区权限

Control Plane 负责 Clone，Runtime 负责编辑。两个容器应使用 UID/GID `1000:1000`，并对 `/workspaces` 可写：

```bash
sudo mkdir -p /data/codeagentx/workspaces
sudo chown -R 1000:1000 /data/codeagentx/workspaces
sudo chmod -R u+rwX,g+rwX /data/codeagentx/workspaces
```

无法统一所有者时使用 ACL：

```bash
sudo setfacl -R -m u:1000:rwx /data/codeagentx/workspaces
sudo setfacl -R -m d:u:1000:rwx /data/codeagentx/workspaces
```

验证：

```bash
docker compose exec control-plane sh -lc 'id && touch /workspaces/cp-test && rm /workspaces/cp-test'
docker compose exec runtime sh -lc 'id && touch /workspaces/runtime-test && rm /workspaces/runtime-test'
```

## GitHub 环境变量

```text
CODEAGENTX_PUBLISHER_MODE=github
CODEAGENTX_GITHUB_TOKEN=...
CODEAGENTX_GITHUB_REPOSITORY=owner/repo
CODEAGENTX_GITHUB_BASE_BRANCH=main
CODEAGENTX_GITHUB_REMOTE_NAME=origin
CODEAGENTX_GITHUB_HEAD_BRANCH_PREFIX=codeagentx/run-
CODEAGENTX_GITHUB_WEBHOOK_SECRET=...
CODEAGENTX_GITHUB_DEFAULT_VERIFICATION_COMMAND=python -m unittest discover -s tests -v
```

检查配置：

```bash
curl -sS http://127.0.0.1:8080/api/config/preflight
```

## 没有公网 IP

SSH 只方便人访问服务器，GitHub Webhook 仍需要可访问的 HTTPS 地址。临时验收可使用 Cloudflare Quick Tunnel：

```bash
docker run --rm --network host cloudflare/cloudflared:latest \
  tunnel --url http://127.0.0.1:8080
```

Webhook URL：

```text
https://<random>.trycloudflare.com/api/webhooks/github
```

Quick Tunnel 不保证稳定或固定域名。长期使用应配置 Named Tunnel、固定域名和后台服务。

## Webhook 配置

- Content type：`application/json`
- Secret：与服务器配置一致
- Events：`Issues`、`Pushes`、`Workflow runs`
- Active：开启

## 运维

```bash
docker compose ps
docker compose logs --tail=200 control-plane
docker compose logs --tail=200 runtime
curl -sS http://127.0.0.1:8080/api/runs/summary
```

停止并保留数据：`docker compose down`。

`docker compose down -v` 会删除命名卷，只能在明确需要清空时执行。

## 已验证结果与常见问题

我们已经在干净 Linux 服务器上验证 Compose、Tunnel、Webhook、Clone、Runtime 修改、测试、审核、Push、PR、CI 回写和最终 `SUCCEEDED`。

- 构建超时：通常是 Docker Hub 或 Maven Central 出口网络；已有镜像可临时 `up -d --no-build`。
- `Permission denied`：检查两个容器 UID、目录 ACL 和新文件默认 ACL。
- `dubious ownership`：只信任当前 Run 的 `safe.directory`，不要使用全局通配符。
- Push 要求用户名：确认镜像包含 Token Push 实现并检查 Token 权限。
- Tunnel 可用但构建失败：Tunnel 只解决入站访问，不能解决服务器出口网络。
