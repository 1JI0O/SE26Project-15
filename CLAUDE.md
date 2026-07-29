# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

本文件同时为项目级硬约束，Claude Code 及其他 AI 助手在本仓库中工作时必须严格遵守。

## Git 提交与合并政策（硬约束）

- 任何 commit、merge 均不得携带 Claude 或其他 AI 的联合作者信息，即禁止出现 `Co-Authored-By: Claude ...` 或类似的 AI 署名 trailer。
- 所有提交只能使用仓库所有者本人的 git 身份（姓名/邮箱），不得添加、保留或恢复任何 AI 身份信息。
- 生成 commit message 时不得包含任何暗示由 AI 生成/协作的署名或标注。
- 若发现历史提交中已包含 AI 署名，应在获得用户明确确认后修正，且修正过程中不得改变代码内容，仅去除署名部分。

## 文档读取

- `*Prototype/` 下的文档不做参考，在编写代码时不以这些文档为参考。
- 参考文档主要使用 `docs/` 下的文档和计划，在对代码进行更新时同步更新 `docs/` 下的文档。
- 架构以 `docs/architecture.md`（按源码核对）为准，接口契约按领域拆分在 `docs/contracts/*.md`（papers、repositories、traces、agent、rag、cloud-sync）。

## 常用命令

仓库包含三个独立构建/测试的部分：`backend/`（本地 FastAPI）、`frontend/`（Vue 3 + Tauri 2）、`server/`（独立账号/同步服务器）。CI（`.github/workflows/ci.yml`）对三者分别执行下述检查，并使用 `uv sync --frozen` / `pnpm install --frozen-lockfile`——修改依赖时必须同步更新对应的 `uv.lock`（backend 与 server 各有一份）或 `pnpm-lock.yaml`，否则 CI 失败。根目录 `Makefile` 提供 `make test` / `make lint` 快捷入口。

### backend（本地 API）

```bash
cd backend
uv sync --extra dev                 # 安装依赖（Python 3.11+，推荐 uv）
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
uv run ruff check app tests         # lint（line-length 100，规则 E/F/I/UP/B）
uv run pytest -q                    # 全部测试
uv run pytest tests/tracing -q      # 单个目录或文件
uv run pytest -q -k "test_name"     # 单个测试
```

### frontend

```bash
cd frontend
pnpm install
pnpm dev            # Vite 开发服务器 127.0.0.1:5173，/api 代理到 127.0.0.1:8000
pnpm typecheck      # vue-tsc --noEmit；前端没有单元测试，CI 检查为 typecheck + build
pnpm build          # vue-tsc + vite build
pnpm desktop:dev    # 先用 PyInstaller 打包后端 sidecar，再启动 Tauri（需 Rust）
pnpm desktop:build  # 构建 macOS app/dmg
```

### server（同步服务器）

```bash
cd server
uv sync --extra dev
uv run ruff check tracelab_server tests
APP_ENV=test DATABASE_URL=sqlite:///./server-test.db \
  CLOUD_BLOB_ROOT=./.test-data/blobs CLOUD_TMP_ROOT=./.test-data/tmp \
  uv run pytest
```

真实 PostgreSQL 集成测试通过 `TEST_POSTGRES_URL` 注入（CI 由 postgres service 提供；该变量缺失时判为配置错误而非静默跳过）。部署用 `server/compose.yaml`，流程见 `server/README.md`。

## 架构要点

TraceLab 是本地优先、单体后端、双运行壳的论文—代码双向追溯工作台。

- 双运行壳共用同一 Vue 前端：Web 模式由 Vite 把 `/api` 代理到 FastAPI（:8000）；Desktop 模式由 Tauri 2（`frontend/src-tauri/src/lib.rs`）启动 PyInstaller 打包的 FastAPI sidecar（:8765，由 `frontend/scripts/build-backend-sidecar.mjs` 构建）。前端统一请求 `/api/v1`。
- backend 分层：`app/api/routes`（领域：projects、papers、repositories、traces、agent、workspace、integration_settings、local_sync、cloud_proxy）+ `app/schemas` → `app/services`（领域业务与异步任务）→ SQLModel/SQLAlchemy（`app/db`，仅 SQLite）。迁移在 FastAPI 启动时自动执行（`app/db/migration_runner.py`，说明见 `app/db/MIGRATIONS.md`）；lifespan 同时恢复中断的仓库分析和 Agent 异步任务。上传与缓存写入 `backend/uploads/`、`backend/data/`。
- 核心服务域（`app/services`）：论文解析（MinerU 本地服务或官方 API，异步任务+本地缓存）、`code_analysis`（安全 ZIP/GitHub 导入、Python AST 分析）、`tensor_flow`（语义张量图）、`tracing` / `trace_suggester`（静态候选 + Agent 双向追溯）、`agent`（会话/记忆持久化、SSE 流式运行、AgentSkills/MCP 能力注册表、写操作需人工确认）、`rag`（论文/代码/已复核追溯案例的语义检索，默认本地离线嵌入，索引由完成钩子自动维护）。
- LLM 可选：任意 OpenAI-compatible 服务，经 `TRACELAB_LLM_*` 配置。未启用时追溯任务保持等待、Agent 不执行写操作；代码分析、张量流、静态追溯完全不依赖 LLM。
- `server/` 是独立产品（`tracelab_server` 包）：只提供账号、Workspace、同步、Blob、维护 Worker 和 `/admin-console`，使用 PostgreSQL 与自己的 Alembic 迁移；不运行 MinerU/代码分析/LLM/Agent，也不进入 Desktop sidecar。前端云端请求经同源 `/cloud-api` 转发；项目在用户明确启用同步前始终 `local_only`。
- frontend 结构：`src/views` + `src/features/`（agent、papers、repository、settings、tensor-flow、tracing）+ Pinia stores；HTTP 经 `src/api` 按领域拆分的 axios client，Agent 流式回复用 SSE fetch。
- 测试约定：backend 测试用内存 SQLite 覆盖依赖注入，并强制关闭 LLM（`backend/tests/conftest.py`）——测试不得访问网络或依赖本机密钥。
- 配置：后端环境变量统一 `TRACELAB_*` 前缀（pydantic-settings）；`.env.example` → `backend/.env` 仅作为首次启动默认值，运行期设置（Agent API、MinerU）保存在本机 SQLite，经设置接口读写且不回传密钥内容。
