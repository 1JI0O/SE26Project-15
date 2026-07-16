# TraceLab 论文代码双向追溯工作台

TraceLab 是面向论文复现与代码审阅的本地工作台。当前技术原型已打通项目创建、MinerU 论文解析、代码仓库导入与静态分析、可交互张量流图、追溯候选审阅，以及带写操作确认的 Agent 接口。Web 与 Tauri 桌面端共用 Vue 3 前端和 FastAPI 后端。

## 技术栈

- 前端：Vue 3、TypeScript、Vite、Element Plus、CodeMirror 6、Axios
- 桌面端：Tauri 2（复用同一前端，提供系统文件选择）
- 后端：FastAPI、Pydantic v2、SQLModel/SQLAlchemy、SQLite
- 论文解析：MinerU 本地服务或 MinerU 官方 API，异步任务与本地缓存
- 代码分析：安全 ZIP/GitHub 导入、`.gitignore`/macOS 元数据过滤、Python AST、语义张量图
- 智能能力：静态追溯基线、可选 OpenAI-compatible LLM、流式 Agent Run、持久化会话/记忆、AgentSkills/MCP 能力注册表、人工确认

## 目录

```text
backend/                 FastAPI、数据库、解析/分析/追溯/Agent 服务
frontend/                Vue Web UI 与 Tauri 2 壳
docs/contracts/          按领域拆分的接口契约
docs/collaboration/      四人协作边界与任务派发
UIPrototype/             迭代材料、模型和演示文档
```

## 环境要求

- Python 3.11 或更高版本，推荐使用 [uv](https://docs.astral.sh/uv/)
- Node.js 20 或更高版本、pnpm 9 或更高版本
- 论文解析二选一：本地 `mineru-api`，或 MinerU 官方 API 令牌
- 构建桌面端时额外安装 Rust 1.77.2+ 和 Tauri 系统依赖；已打包应用的使用者不需要安装 Python、Node.js 或 Rust

## 配置

Web 与桌面端启动后，点击右上角的设置按钮即可配置 Agent API 和 MinerU。设置保存在本机 SQLite 应用数据中，保存后无需重启；读取接口只返回密钥是否已配置，不会回传密钥内容。桌面端日常使用不需要编辑 `.env`。

`.env` 仅作为首次启动默认值和无前端部署时的兼容配置：

```bash
cp .env.example backend/.env
```

默认使用本地 MinerU：

```bash
mineru-api --host 127.0.0.1 --port 8001 --enable-vlm-preload true
```

若以无前端方式使用官方 API，可修改 `backend/.env`：

```dotenv
TRACELAB_MINERU_PROVIDER=official
TRACELAB_MINERU_API_TOKEN=<your-token>
```

LLM 默认关闭；静态追溯仍可运行。无前端部署启用 OpenAI-compatible 服务时配置：

```dotenv
TRACELAB_LLM_ENABLED=true
TRACELAB_LLM_BASE_URL=https://example.com/v1
TRACELAB_LLM_API_KEY=<your-key>
TRACELAB_LLM_MODEL=<model-name>
```

DeepSeek V4 的 JSON 模式还应设置 `TRACELAB_LLM_THINKING_MODE=disabled`；其他服务不支持该扩展字段时保持为空。

DeepSeek V4 示例：

```dotenv
TRACELAB_LLM_BASE_URL=https://api.deepseek.com
TRACELAB_LLM_MODEL=deepseek-v4-flash
TRACELAB_LLM_THINKING_MODE=disabled
```

不要将令牌提交到 Git。应用内填写的密钥保存在本机数据库中，应同时保护操作系统账号和应用数据目录；当前技术原型尚未接入系统钥匙串。完整 MinerU 参数见 [论文解析契约](docs/contracts/papers.md)，追溯与 LLM 参数见 [追溯契约](docs/contracts/traces.md)。

## 启动 Web 版

终端 1：

```bash
cd backend
uv sync --extra dev
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

终端 2：

```bash
cd frontend
pnpm install
pnpm dev
```

打开 `http://127.0.0.1:5173`。Vite 会把 `/api` 代理到 `http://127.0.0.1:8000`；OpenAPI 文档位于 `http://127.0.0.1:8000/docs`。

### Windows（PowerShell）启动 Web 版

在 Windows 10/11 上安装 Python 3.11+、[uv](https://docs.astral.sh/uv/)、Node.js 20+ 和 pnpm 9+ 后，在仓库根目录分别打开两个 PowerShell 窗口。首次启动可先复制默认配置：

```powershell
Copy-Item .env.example backend\.env
```

终端 1 启动后端：

```powershell
Set-Location backend
uv sync --extra dev
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

终端 2 启动前端：

```powershell
Set-Location frontend
pnpm install
pnpm dev
```

浏览器打开 `http://127.0.0.1:5173`。若需要本地论文解析，另开一个终端运行 `mineru-api --host 127.0.0.1 --port 8001 --enable-vlm-preload true`，或在应用设置中改用 MinerU 官方 API。

## 启动桌面版

开发模式会先把 FastAPI 构建为本机后端运行目录，再由 Tauri 自动启动前端和后端：

```bash
cd frontend
pnpm install
pnpm desktop:dev
```

构建可独立运行的 macOS 应用：

```bash
cd frontend
pnpm install
pnpm desktop:build
```

构建完成后可直接运行：

```bash
open "src-tauri/target/release/bundle/macos/TraceLab.app"
```

同时会生成以下安装产物：

```text
frontend/src-tauri/target/release/bundle/macos/TraceLab.app
frontend/src-tauri/target/release/bundle/dmg/TraceLab_0.1.0_aarch64.dmg
```

### Windows 桌面版

桌面开发需要额外安装 Rust stable（`x86_64-pc-windows-msvc` 工具链）和 Visual Studio 2022 的“使用 C++ 的桌面开发”工作负载；Windows 10/11 通常已自带 Microsoft Edge WebView2 Runtime，缺失时需先安装。安装好 Python、uv、Node.js 和 pnpm 后，在 PowerShell 中运行：

```powershell
Set-Location frontend
pnpm install
pnpm desktop:dev
```

该命令会打包并启动内置 FastAPI 后端，然后启动 Tauri 窗口；不需要另行启动 Uvicorn。首次运行会下载 Rust/Python/Node 依赖，耗时较长。

要生成可安装的 Windows 包，请在 Windows 主机上执行：

```powershell
Set-Location frontend
pnpm install
pnpm exec tauri build --bundles nsis
```

安装程序输出在 `frontend\src-tauri\target\release\bundle\nsis\`；安装后从开始菜单启动 TraceLab。当前包未进行 Windows 代码签名，首次运行可能出现 SmartScreen 提示。桌面数据保存在 `%LOCALAPPDATA%\com.se26project.tracelab\`；启动失败时可查看其中的 `startup-error.log`。

应用内已包含 FastAPI 后端和展开后的 Python 运行目录，启动和退出由 Tauri 自动管理，不会在每次启动时重复解压。桌面数据保存在 `~/Library/Application Support/com.se26project.tracelab/`。当前本地构建使用 ad-hoc 签名并启用 Hardened Runtime，产物面向 Apple Silicon。为 Intel Mac、Windows 或 Linux 分发时，应在对应目标平台重新构建。对外分发 macOS 安装包时，应改用 Developer ID 并完成公证。

MinerU 官方 API 可直接在设置窗口配置。选择“本地 MinerU”时，模型推理服务仍是可选外部依赖，需要在设置的地址运行 `mineru-api`；这不影响项目管理、代码分析和其他本地功能。

## 演示闭环

1. 新建项目并进入工作台。
2. 上传 PDF；前端提交 MinerU 异步任务并显示 queued/running/succeeded/failed 状态。
3. 上传 ZIP 或输入公开 GitHub 仓库地址；检查过滤后的完整文件树与分析摘要。
4. 打开并编辑文本代码文件；保存后仓库修订号递增，旧追溯关系自动标记 stale。
5. 查看主模型的分层架构图，双击自定义模块下钻；需要排查时切换算子调试图，点击节点可跳转到对应代码。
6. 生成追溯候选并人工接受或拒绝；未配置 LLM 时自动降级为静态结果。
7. 在 Agent 侧栏连续对话；可新建、重命名和归档会话，并管理项目/跨项目记忆。Agent 可读取当前论文、代码、架构图和追溯证据，定位代码或聚焦架构图。
8. Agent 回答通过 SSE 逐步显示，同时展示可审计的进度摘要和工具交互；重复的成功读取会复用证据，达到预算后强制收敛为结论。
9. Agent“能力”页可查看和开关内置/外部 Skill 与 Tool。外部能力默认关闭且不受信任；保存代码、重跑分析、创建/更新追溯关系仍须人工确认。
10. 上传大型仓库或保存代码后，架构图在后台生成并持久化；打开流程图只读取缓存，分析完成后 UI 自动刷新。
11. 通过右上角设置窗口切换 Agent 服务或 MinerU 本地/官方接入，无需重启。
12. 返回项目入口，点击“批量管理”，可全选或勾选多个项目并永久删除其关联数据。

“魔改冲突分析”和“报告文件导出”当前仅保留稳定 UI/接口，不应视为算法已实现。

## 构建与测试

```bash
cd backend
uv run ruff check .
uv run python -m pytest -q

cd ../frontend
pnpm typecheck
pnpm build
```

SQLite 表结构迁移会在 FastAPI 启动时自动执行。开发数据默认写入 `backend/data/` 和 `backend/uploads/`（取决于启动工作目录与 `.env` 配置）。

## 外部 Agent 能力

TraceLab 直接发现符合 AgentSkills `SKILL.md` 约定的目录。可放入仓库根目录 `skills/<name>/SKILL.md`、`~/.tracelab/skills/` 或 `~/.openclaw/skills/`。其他目录可通过 `TRACELAB_AGENT_SKILL_ROOTS` 显式追加。外部 Skill 首次出现时不会自动进入 Agent 上下文，需要在 Agent 侧栏“能力”页同时启用并标记为可信。

外部可调用工具通过 `plugins/<plugin>/tracelab.plugin.json` 声明 HTTP MCP server。TraceLab 会读取 `tools/list` 的 JSON Schema，并在执行前后校验参数/结构化输出；外部写工具沿用人工确认。完整格式和安全边界见 [Agent 契约](docs/contracts/agent.md)。

## 接口文档

- [接口总览](docs/api-contract.md)
- [论文解析与 MinerU](docs/contracts/papers.md)
- [代码仓库、编辑与张量流](docs/contracts/repositories.md)
- [追溯生命周期与 LLM 降级](docs/contracts/traces.md)
- [Agent 与写操作确认](docs/contracts/agent.md)
