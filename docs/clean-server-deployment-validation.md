# 干净 Linux 服务器部署验收记录

## 验收范围

在没有 CodeAgent-X 历史环境的 Linux 服务器上，从源码和 `.env` 启动完整 Compose 服务，并验证外部 Webhook、仓库工作区和 GitHub 工作流。

## 已验证环境

- Docker Engine 与 Compose v2；
- PostgreSQL、Python Runtime、Spring Boot Control Plane；
- 独立宿主机数据目录和工作区目录；
- 无公网 IP，通过 Cloudflare Tunnel 接收 GitHub Webhook。

## 验收结果

```text
Compose services        PASS
Database health         PASS
Runtime health          PASS
Control-plane health    PASS
GitHub webhook ping     PASS
Webhook signature       PASS
Repository clone        PASS
Runtime workspace write PASS
Agent patch             PASS
Verification            PASS
Human review            PASS
Branch / commit / push  PASS
Pull request            PASS
GitHub Actions CI       PASS
CI status writeback     PASS
Final SUCCEEDED         PASS
```

## 关键经验

### 统一容器用户

Control Plane 和 Runtime 应使用相同 UID/GID。仅修改宿主机目录所有者但容器 UID 不一致，仍会导致 Runtime 无法修改 Clone 出来的文件。

### 使用 ACL 处理共享目录

当宿主机所有者不能调整时，为 Runtime UID 设置当前 ACL 和默认 ACL，确保新 Clone 的文件也继承写权限。

### Git 安全与身份

- 只将当前 Run 工作区加入 `safe.directory`；
- Control Plane 容器配置提交姓名和邮箱；
- 使用非交互式 Token 推送，不把 Token 写入 Git Remote。

### Tunnel 只解决入站访问

Cloudflare Tunnel 允许 GitHub 访问没有公网 IP 的服务器，但不能修复服务器访问 Docker Hub、Maven Central 或 GitHub 的出口网络问题。

## 最终结论

干净服务器部署和真实 GitHub PR/CI 闭环均已完成。曾出现的镜像仓库、Maven 和 Quick Tunnel 超时属于网络环境波动；网络恢复后没有发现剩余业务逻辑缺陷。
