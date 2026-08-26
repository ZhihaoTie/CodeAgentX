# 本地 Compose 验收记录

## 目的

本记录说明本地 Compose 部署已经验证的能力。操作步骤以 [部署指南](deployment-compose.md) 为准。

## 拓扑

- Control Plane：对宿主机暴露 `8080`；
- Runtime：Compose 内部 `8765`；
- PostgreSQL：Compose 内部 `5432`；
- Control Plane 与 Runtime：共享 `/workspaces`。

## 已验证项目

| 项目 | 结果 | 验证方式 |
| --- | --- | --- |
| 三个容器启动 | 通过 | `docker compose ps` |
| 数据库与 Runtime 健康 | 通过 | `GET /api/health` |
| 配置预检 | 通过 | `GET /api/config/preflight` |
| 运行指标 | 通过 | `GET /api/metrics` |
| Request ID | 通过 | 响应头 `X-Request-Id` |
| Generic REST | 通过 | `run_compose_generic_callback_smoke.py` |
| 回调记录 | 通过 | Callback Delivery 审计 |
| 重启恢复 | 通过 | `run_compose_restart_smoke.py` |
| Webhook 幂等 | 通过 | 重复 Issue / workflow_run Smoke |
| Runtime 超时 | 通过 | `run_timeout_smoke.py` |
| 提交重试 | 通过 | `run_runtime_submit_retry_smoke.py` |
| 并发限制 | 通过 | `run_concurrency_limit_smoke.py` |

## 常用验收命令

```bash
python demos/run_compose_smoke.py
python demos/run_compose_restart_smoke.py
python demos/run_compose_generic_callback_smoke.py
```

Windows 可使用：

```powershell
py -3.13 -B demos/run_compose_smoke.py
```

## 结果边界

本记录证明单机 Compose 拓扑和平台接口可用，不代表 Kubernetes、大规模并发或不可信多租户生产环境已经验证。真实 GitHub 云端结果见 [最终验收记录](final-validation.md)。
