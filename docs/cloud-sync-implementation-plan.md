# TraceLab 账号与基础同步实施说明

> 状态：独立服务器源码和本地后端解耦已完成；生产 feature flag 仍默认关闭。只有真实
> PostgreSQL 16 staging、SMTP、磁盘阈值和外部备份恢复验收全部通过后，才允许生产开启。

本文说明当前代码入口和部署方式。架构约束见
[`cloud-sync-architecture.md`](cloud-sync-architecture.md)，重构审查记录见
[`server-deployment-refactor-plan.md`](server-deployment-refactor-plan.md)。

## 1. 运行边界

| 产品 | 入口 | 职责 |
|---|---|---|
| Local API | `backend/app/main.py` | SQLite、本地文件、论文解析、代码分析、TraceLink、Agent、本地 outbox/inbox |
| 应用前端 | `frontend/src/**` | 本地 Web 与 Tauri Desktop 的完整工作台；通过 `localHttp`/`cloudHttp` 分别连接本地和远程 API |
| Sync Server API | `server/tracelab_server/main.py` | 账号、Workspace、项目同步、Blob、管理员 API 和最小管理员控制台 |
| Maintenance Worker | `server/tracelab_server/worker.py` | 邮件、Blob/tombstone GC、事件压缩；不执行解析、分析或 Agent |

完整 Vue 前端不部署到服务器。服务器 Docker build context 固定为 `server/`，不复制
`frontend/` 或 `backend/`。Local 与 Server 使用独立 Python 包、依赖、metadata 和 Alembic
chain，只通过冻结的 `/api/v1` 契约通信。

本地历史 SQLite migration 保持不变，已有项目升级后仍是 `local_only`。服务器不接收 SQLite
文件，也不会自动上传任何旧项目。

## 2. 已实现能力

- 邮箱/密码注册登录、邮箱验证、密码重置、设备管理、15 分钟 access token 和旋转的 30 天
  refresh token；密码使用 Argon2id，数据库只保存 token 哈希。
- Workspace 和 `owner/editor/viewer`；项目、同步、Blob 均以 Workspace 为授权边界。
- Project、Paper、Repository、代码编辑、TraceLink、Agent Conversation/Message/Run/Event/Memory
  的 UUID/版本同步。
- `bootstrap/push/pull/ack`、逐操作事务、workspace sequence、幂等 receipt、显式 conflict、
  设备 cursor 和至少 30 天 tombstone。
- `local_only/cloud_enabled/cloud_paused/cloud_detached`；paused 只影响当前设备，detach 不删除
  云端项目。
- Blob 分块上传、断点位置、SHA-256、MIME/PDF/ZIP 校验、Workspace UUID 句柄、全局物理
  去重、不可变 artifact version、Range 下载、配额和宽限期 GC。
- `/api/v1/admin/*` 兼容现有 Desktop 管理入口；`/admin-console` 是 server-owned Jinja2
  管理页面，只显示账号、Workspace、项目元数据、用量、任务和审计。
- 管理员控制台使用独立 opaque session、`HttpOnly; SameSite=Strict` Cookie 和 CSRF，数据库
  只保存会话/CSRF 哈希。

服务器明确不提供 PDF/源码/TraceLink 正文/Agent 正文的管理员读取接口，也不提供任意 SQL、
文件浏览或 Shell。

## 3. 目录与迁移

```text
backend/                   Local API 与 SQLite
  app/models/sync.py       local outbox/inbox/state/conflict
frontend/                  本地 Web/Tauri 完整应用前端
server/                    可独立复制部署的服务器产品
  compose.yaml
  Dockerfile
  .env.example
  tracelab_server/
  tests/
  deploy/
```

Server baseline 位于
`server/tracelab_server/db/migrations/versions/0001_server_baseline_server_baseline.py`，显式创建
表、索引、外键和约束，不调用 runtime metadata `create_all`。Compose 使用一次性 migrator；
API/Worker 等待迁移成功，普通启动不 drop/rebuild 数据。

## 4. 部署

1. 在 Linux 主机准备 `/srv/tracelab/postgres`、`/srv/tracelab/blobs`、
   `/srv/tracelab/tmp`，分别用 LVM/project quota 限制约 8 GB、25 GB、4 GB。
2. 进入 `server/`，复制 `.env.example` 为 `.env`，配置生产域名、强随机 JWT secret、数据库
   密码、SMTP、应用账号链接地址和服务器外 `BACKUP_REMOTE`。
3. 为域名准备 `/etc/letsencrypt/live/<domain>` 证书。
4. 保持 `CLOUD_SYNC_FEATURE_ENABLED=false`，执行：

   ```bash
   docker compose --env-file .env up -d postgres
   docker compose --env-file .env run --rm migrator
   docker compose --env-file .env up -d api worker proxy
   ```

5. 一次性创建平台管理员：

   ```bash
   docker compose --env-file .env run --rm api \
     python -m tracelab_server.cli create-admin --email admin@example.com
   ```

6. 验证 `https://<domain>/api/v1/health` 和 `/admin-console/login`，执行备份与空库恢复演练。
7. staging 全部验收后才将 feature flag 改为 `true` 并重启 API/Worker。

Compose 只发布 Nginx 的 80/443；PostgreSQL、API、Worker 和 Blob 不发布公网端口。Nginx
认证日志不记录 query，认证和下载路径分别限流。

## 5. 备份和维护

- `server/deploy/backup.sh`：每日 custom-format `pg_dump`、7 个日备份、4 个周备份，以及 Blob
  不可变增量复制到外部 rclone target。
- `server/deploy/restore-verify.sh`：只允许恢复到空验证数据库和空 Blob 目录，并逐条核对
  ready Blob 的物理文件。
- `server/deploy/rebuild-cloud.sh`：需要精确确认字符串的显式破坏性维护入口；普通启动绝不调用。
- 80% 磁盘使用率告警；90% 时拒绝新上传和派生 Blob，但继续允许登录、pull、下载和删除。

## 6. 验证命令

```bash
cd backend
uv sync --frozen --extra dev
uv run ruff check app tests
uv run pytest -q

cd ../server
uv sync --frozen --extra dev
uv run ruff check tracelab_server tests
uv run pytest -q

cd ../frontend
pnpm typecheck
pnpm build
```

CI 分为 `local-backend`、`sync-server`、`frontend` 三个 Job。`sync-server` 固定启动
PostgreSQL 16 并注入 `TEST_POSTGRES_URL`；CI 中缺少该变量会直接失败，不允许静默 skip。

## 7. 尚未完成的生产验收

当前仓库不包含生产域名证书、SMTP 凭据、外部备份账号和目标服务器 quota 配置，因此不能宣告
生产就绪。上线前必须完成：

- 真实 PostgreSQL 16 migration、并发 sequence 和 `FOR UPDATE SKIP LOCKED`；
- 两台 Desktop 对显式启用项目的 Project/Paper/Repository/TraceLink/Agent 双向同步；
- paused/detach、冲突、断网重试、文件双版本和跨 Workspace 去重 GC；
- 90% 停传、7/4 备份保留和 PostgreSQL + Blob 空环境恢复；
- 正式 SMTP 邮箱验证、HTTPS/Origin/CSRF 和跨 Workspace 越权测试。
