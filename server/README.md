# TraceLab Sync Server

该目录是独立的 TraceLab 账号与同步服务器。它只提供 `/api/v1`、Blob、维护 Worker
和 `/admin-console`，不会构建 `frontend/`，也不会运行论文解析、代码分析或 Agent/LLM。

## 部署

1. 准备 Linux 主机、域名、HTTPS 证书、SMTP 和服务器之外的 rclone 备份目标。
2. 创建 `/srv/tracelab/postgres`、`/srv/tracelab/blobs`、`/srv/tracelab/tmp`，分别配置约
   8 GB、25 GB、4 GB 的 LVM/project quota。Blob/tmp 目录需允许容器内 UID/GID 10001
   写入；PostgreSQL 目录按官方镜像初始化权限，不要设置为全局可写。
3. 复制 `.env.example` 为 `.env`，填写强随机密钥、数据库密码、域名、SMTP 和备份目标。
4. 首次保持 `CLOUD_SYNC_FEATURE_ENABLED=false`，运行迁移和服务：

   ```sh
   docker compose --env-file .env up -d postgres
   docker compose --env-file .env run --rm migrator
   docker compose --env-file .env up -d api worker proxy
   ```

5. 一次性创建管理员（命令会交互读取密码）：

   ```sh
   docker compose --env-file .env run --rm api \
     python -m tracelab_server.cli create-admin --email admin@example.com
   ```

6. 验证 `/api/v1/health`、`/admin-console/login`、外部备份及恢复演练后，再将 feature flag
   改为 `true` 并重启 API/Worker。

Compose 只发布 Nginx 的 80/443。PostgreSQL、API、Worker 和 Blob 目录均位于私有网络或
宿主机持久化目录，不发布公网端口。普通启动只执行显式 Alembic migration，不会删除数据。

## 本地开发与测试

```sh
uv sync --extra dev
APP_ENV=test DATABASE_URL=sqlite:///./server-test.db \
  CLOUD_BLOB_ROOT=./.test-data/blobs CLOUD_TMP_ROOT=./.test-data/tmp \
  uv run pytest
uv run ruff check tracelab_server tests
```

真实 PostgreSQL 集成测试通过 `TEST_POSTGRES_URL` 注入；CI 中该变量缺失时应判为配置错误，
而不是静默跳过。

## 维护

- 手动备份：`docker compose --env-file .env --profile maintenance run --rm backup`
- 外部恢复校验：`deploy/restore-verify.sh`（只接受空验证库和空 Blob 目录）
- 重建：`deploy/rebuild-cloud.sh` 是显式破坏性维护入口，绝不由启动流程调用。
