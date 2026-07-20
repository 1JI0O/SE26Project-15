# TraceLab 云端账号与同步实施说明

本文是 `cloud-sync-architecture.md` 的实现落点。架构文档中的安全、容量和本地优先约束仍是权威规则；本文说明代码入口、交付顺序和验收方法。
字段、权限矩阵与端点约束见 [`contracts/cloud-sync.md`](contracts/cloud-sync.md)。

## 运行入口

| 模式 | 入口 | 数据与职责 |
|---|---|---|
| Local API | `app.main:app` | SQLite、本地绝对路径、离线解析/分析、本地 outbox/inbox；仅绑定 loopback |
| Cloud API | `app.cloud:app` | PostgreSQL、账号、workspace、UUID 项目、同步、Blob、管理员；生产必须 HTTPS |
| Cloud Worker | `python -m app.worker` | PostgreSQL 任务领取、重试、解析/分析适配、墓碑与 Blob 维护 |

Cloud API 不装配本地集成设置或整数项目路由；Local API 不暴露云端账号表和管理员接口。两种 API 共享 Pydantic 同步契约和纯分析逻辑，不传输 SQLite 文件。

Desktop 构建时默认绑定统一云端 `https://10.119.5.94/api/v1`（见
`frontend/.env.desktop`）。终端用户无需自行配置远程服务器；本地工作台可不登录离线使用，
登录后按项目启用同步。平台管理员登录后可通过顶栏「管理」进入账号/配额/运维界面。

若需临时指向其他 staging，可覆盖为 `.env.desktop.local` 中的
`VITE_CLOUD_API_BASE_URL`；未覆盖时始终使用上述统一服务器。

## 已实现的领域边界

- 本地 Project、Paper、Repository、TraceLink 拥有 public UUID 和版本；已有项目迁移后保持 `local_only`。
- 账号使用 Argon2id；access token 15 分钟，refresh token 30 天并旋转，数据库只保存哈希。
- Browser refresh token 使用 Secure/HttpOnly/SameSite Cookie；Desktop 使用操作系统凭据库。
- Cloud API 的项目、同步和 Blob 请求必须先通过用户、有效会话、邮箱验证和 workspace role 检查。
- workspace sequence、领域修改、sync event 和 receipt 在单个事务内提交；删除生成至少 30 天墓碑。
- PDF/ZIP 先写 quarantine，校验大小、MIME、SHA-256 和 ZIP 安全后进入内容寻址目录。
- 云端任务通过 PostgreSQL `FOR UPDATE SKIP LOCKED` 领取；没有 Redis、MinIO 或 Kubernetes 依赖。
- 管理员接口只返回账号、配额、任务、存储和审计摘要，不提供项目正文读取能力。

## 交付阶段

1. C0/C1：运行模式、迁移、Compose、Nginx、PostgreSQL、Blob、Worker、备份入口。
2. C2：注册登录、验证/重置、设备、workspace/member、管理员和统一授权。
3. C3：本地 outbox/inbox、bootstrap/push/pull/ack、幂等回执、冲突和墓碑。
4. C4：分块 Blob、断点续传、去重、配额、Range 下载和数据库任务。
5. C5：Cloud Web、Desktop 双 client、系统凭据、显式同步授权、暂停和冲突提示。

每阶段都必须保持 Local API 测试通过。任何没有 `cloud_enabled` 的项目不得出现在本地 outbox；云端不可返回本地路径或第三方 API key。

## 部署

1. 准备 Linux 主机的 `/srv/tracelab/postgres`、`/srv/tracelab/blobs`、`/srv/tracelab/tmp`，权限仅授予容器运行账号。生产环境必须把它们放在分别限额约 8 GB、25 GB、4 GB 的 LVM volume 或项目 quota 上，而不是仅创建同一分区中的普通目录；剩余空间留给系统、镜像与日志。
2. 复制 `.env.cloud.example` 为 `.env.cloud`，设置域名、随机 JWT 密钥、数据库密码、SMTP 和服务器外 `BACKUP_REMOTE`。
3. 预先为域名签发证书并挂载到 `/etc/letsencrypt/live/<domain>`。
4. 执行 `docker compose --env-file .env.cloud up -d --build`；随后用 `docker compose --env-file .env.cloud exec api python -m app.cli create-admin --email <email>` 创建首个管理员。

当前实现补充说明：Compose 使用一次性 `migrator`，API/Worker 仅在迁移成功后启动；普通启动不会重建数据。Web 与 Desktop 写操作统一进入 Cloud Domain Command Service，设备暂停保存在 `device_project_binding`，不会修改其他设备或 Web 的项目状态。

Local SQLite 与 Cloud PostgreSQL 使用独立 Alembic chain。新建 SQLite 只创建本地领域和 outbox/inbox 表；历史 SQLite 中已经存在的空云端表会原样保留但不再迁移或引用。Cloud baseline 只创建账号、Workspace、云端领域、同步、Blob 和任务表；检测到旧的混合 schema 时迁移器会停止并要求执行显式维护重建流程。
5. 安装 `deploy/tracelab-backup.service` 和 `.timer`，首次上线前执行一次备份及恢复演练。
6. `.env.cloud` 中的 `CLOUD_SYNC_FEATURE_ENABLED` 初始保持 `false`；仅在 staging 连续运行、SMTP、磁盘阈值和恢复演练全部通过后改为 `true` 并重启 API。

恢复演练必须使用独立的空数据库和空目录，禁止覆盖生产数据。设置
`RESTORE_DB_DUMP_REMOTE`、`RESTORE_BLOB_REMOTE`、`RESTORE_DATABASE_URL`、
`RESTORE_BLOB_ROOT` 后运行 `sh deploy/restore-verify.sh`；脚本会恢复 PostgreSQL、
下载 Blob，并逐条检查数据库中的 ready Blob 引用是否存在。

生产就绪要求：只有 80/443 对外、PostgreSQL 无宿主端口、SMTP 可用、外部备份成功、90% 磁盘阈值测试通过，并完成跨 workspace 越权测试。

## 验证命令

```bash
cd backend
uv run ruff check app tests
uv run python -m pytest -q

cd ../frontend
pnpm typecheck
pnpm build

cd src-tauri
cargo check

cd ../..
CLOUD_ENV_FILE=.env.cloud.example docker compose --env-file .env.cloud.example config --quiet
```

PostgreSQL 迁移和 `SKIP LOCKED` 并发测试应在 staging 使用 PostgreSQL 16 运行；SQLite 测试只验证 Local API 和协议逻辑，不能替代生产数据库验证。

## 当前验收状态

- 后端完整回归、云端账号/权限/同步/Blob/Worker/冲突与新建 SQLite 迁移测试通过。
- 当前开发机未提供可用的 PostgreSQL 16 服务，因此真实 PostgreSQL 用例在本机跳过。CI 已固定
  PostgreSQL 16，且 CI 缺少 `TEST_POSTGRES_URL` 时会直接失败，不允许静默 skip；目标 staging
  仍必须完成迁移、并发 sequence 和 `FOR UPDATE SKIP LOCKED` 实测。
- Vue TypeScript 检查和生产构建、Tauri Rust `cargo check`、Compose 展开、备份与恢复脚本
  shell 语法检查通过。
- 当前仓库没有生产 SMTP 凭据、域名证书或外部备份账号，因此不宣告生产就绪；
  `.env.cloud.example` 也有意保持 `CLOUD_SYNC_FEATURE_ENABLED=false`。
