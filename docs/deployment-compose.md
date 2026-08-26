# Docker Compose 部署指南

本文说明如何在单机或 Linux 服务器上部署 CodeAgent-X。当前方案刻意保持简单，不依赖 Kubernetes、消息队列或外部可观测平台。

## 部署拓扑

```text
GitHub / 调用方
      │ HTTP / Webhook
      ▼
Control Plane :8080
      │ Compose 私有网络
      ├──────────────► Runtime :8765
      │                    │
      │              shared /workspaces
      ▼
PostgreSQL :5432
```

默认只有 `8080` 暴露到宿主机。Runtime 和 PostgreSQL 仅在 Compose 网络内可访问。

## 环境要求

- Docker Engine 与 Docker Compose v2；
- 能访问 GitHub；
- 构建时能访问 Docker Hub 和 Maven Central；
- GitHub 模式需要具有目标仓库权限的 Token；
- 接收 Webhook 需要公网域名、反向代理或 Tunnel。

## 快速启动

```bash
git clone https://github.com/ZhihaoTie/CodeAgentX.git codeagentx-deploy
cd codeagentx-deploy
cp .env.example .env
```

编辑 `.env` 后启动：

```bash
docker compose up -d --build
docker compose ps
curl -sS http://127.0.0.1:8080/api/health
```

健康响应应包含：

```json
{
  "status": "ok",
  "database": "ok",
  "runtime": "ok"
}
```

## 推荐服务器目录

```text
/data/codeagentx/
├── deploy/       # 项目源码和 Compose 文件
├── postgres/     # PostgreSQL 数据
└── workspaces/   # 目标仓库工作区
```

在 `.env` 中使用绝对路径：

```text
CODEAGENTX_POSTGRES_DATA_VOLUME=/data/codeagentx/postgres
CODEAGENTX_WORKSPACES_VOLUME=/data/codeagentx/workspaces
```

## 工作区权限

Control Plane 负责克隆，Runtime 负责编辑，两者必须对同一个 `/workspaces` 可写。镜像中的 `codeagentx` 用户使用 UID/GID `1000:1000`。

```bash
sudo mkdir -p /data/codeagentx/workspaces
sudo chown -R 1000:1000 /data/codeagentx/workspaces
sudo chmod -R u+rwX,g+rwX /data/codeagentx/workspaces
```

若宿主机或已有文件的 UID 无法统一，可设置 ACL：

```bash
sudo setfacl -R -m u:1000:rwx /data/codeagentx/workspaces
sudo setfacl -R -m d:u:1000:rwx /data/codeagentx/workspaces
```

验证两个服务均可写：

```bash
docker compose exec control-plane sh -lc 'id && touch /workspaces/cp-test && rm /workspaces/cp-test'
docker compose exec runtime sh -lc 'id && touch /workspaces/runtime-test && rm /workspaces/runtime-test'
```

## GitHub 配置

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

不要把 `.env`、Token 或 Webhook Secret 提交到 Git。

检查配置是否就绪：

```bash
curl -sS http://127.0.0.1:8080/api/config/preflight
```

## 没有公网 IP

GitHub 必须主动访问 Webhook，因此仅有 SSH 不能完成自动触发。可以使用 Cloudflare Tunnel：

```bash
docker run --rm --network host cloudflare/cloudflared:latest \
  tunnel --url http://127.0.0.1:8080
```

将返回的 HTTPS 地址配置为：

```text
https://<random>.trycloudflare.com/api/webhooks/github
```

Quick Tunnel 适合验收，不保证固定域名或可用性。长期使用应创建 Named Tunnel、固定域名，并将 Tunnel 作为服务运行。

## Webhook 设置

- Payload URL：外部 HTTPS 地址加 `/api/webhooks/github`
- Content type：`application/json`
- Secret：与 `CODEAGENTX_GITHUB_WEBHOOK_SECRET` 相同
- Events：`Issues`、`Pushes`、`Workflow runs`
- Active：启用

GitHub 的 Ping 显示成功后，再创建测试 Issue。

## 运维检查

```bash
docker compose ps
docker compose logs --tail=200 control-plane
docker compose logs --tail=200 runtime
curl -sS http://127.0.0.1:8080/api/runs/summary
```

只重启服务：

```bash
docker compose restart
```

停止但保留数据：

```bash
docker compose down
```

`docker compose down -v` 会删除命名卷，只能在明确需要清空数据时使用。

## 常见问题

### 构建阶段网络超时

Docker Hub 或 Maven Central 超时属于出口网络问题。已有镜像时可先使用：

```bash
docker compose up -d --no-build
```

它不会包含尚未构建进镜像的新代码。

### `dubious ownership`

确认容器 UID 和工作区权限一致。CodeAgent-X 会针对当前 Run 设置 `safe.directory`，不建议使用全局 `safe.directory=*`。

### Git Push 要求用户名

确认部署镜像包含 Token Push 实现，并检查 Token 权限。CodeAgent-X 使用非交互式凭据，不应把 Token 写进 Remote URL。
