# TraceLab 论文代码双向追溯工作台

TraceLab 提供两种客户端形态：

- **桌面端**：适合独立使用，以 Tauri 安装包交付。
- **VS Code 插件**：直接在代码工作区中完成论文解析、代码分析与双向追溯。

另有可选的 **TraceLab Sync Server**，用于桌面端账号、项目同步、Blob 存储和管理员操作。
桌面端不登录服务器也可使用本地项目；VS Code 插件当前使用工作区内的 `.tracelab/`
目录，不连接同步服务器。

## 选择部署方式

| 组件 | 支持平台 | 适用场景 | 是否需要服务器 |
| --- | --- | --- | --- |
| 桌面端 | macOS、Windows、Linux | 完整的独立图形界面 | 否；云同步时需要 |
| VS Code 插件 | macOS、Windows、Linux | 在现有代码工作区内使用 | 否 |
| Sync Server | Linux 生产服务器 | 账号、同步、Blob 和管理控制台 | 本身即服务器 |

> 桌面端安装包包含运行所需组件。最终用户无需安装 Python、Node.js 或 Rust，也无需另行
> 启动本地网页或服务进程。

## 仓库目录

```text
frontend/                Vue 3 + Tauri 2 桌面客户端
server/                  TraceLab Sync Server 与 Docker Compose 部署配置
vscode-extension/        VS Code 插件
packages/tracelab_core/  VS Code 插件使用的分析 CLI
scripts/                 插件运行时打包与端到端检查脚本
docs/                    设计、契约与部署补充文档
```

## 桌面端

### 安装已构建版本

桌面安装包与生成它的操作系统和 CPU 架构绑定，请选择匹配的平台产物。

| 平台 | 安装产物 | 安装与启动 |
| --- | --- | --- |
| macOS | `.dmg` / `.app` | 打开 DMG，将 TraceLab 拖入“应用程序”，再从 Launchpad 或 Finder 启动 |
| Windows | NSIS `.exe` | 运行安装程序，然后从开始菜单启动 TraceLab |
| Debian/Ubuntu | `.deb` | 运行 `sudo apt install ./TraceLab_*.deb`，再从应用菜单启动 |
| 其他主流 Linux | `.AppImage` | `chmod +x TraceLab_*.AppImage` 后运行该文件 |

开发构建目前未进行正式代码签名。macOS 对外分发应使用 Developer ID 签名并完成公证，
否则 Gatekeeper 可能阻止启动；Windows 对外分发应使用代码签名证书，否则 SmartScreen
可能显示安全提示。

### 日常使用

1. 启动 TraceLab，新建项目。
2. 导入论文 PDF，并在“设置”中选择 MinerU 官方 API 或可访问的 MinerU 服务。
3. 导入代码 ZIP 或公开 GitHub 仓库，等待代码分析完成。
4. 在“设置”中配置 OpenAI-compatible LLM 地址、模型和密钥。
5. 生成追溯关系，在论文、代码、追溯矩阵与张量流图之间查看和审阅结果。
6. 如需多设备同步，登录账号，并在项目列表中为指定项目启用云同步。

MinerU 与 LLM 密钥不要提交到 Git。不登录服务器时，项目保持在当前设备；启用同步前请先
确认项目中允许上传的论文、代码和其他数据范围。

桌面端数据和启动错误日志位于系统应用数据目录：

| 平台 | 默认目录 |
| --- | --- |
| macOS | `~/Library/Application Support/com.se26project.tracelab/` |
| Windows | `%APPDATA%\com.se26project.tracelab\` |
| Linux | `${XDG_DATA_HOME:-~/.local/share}/com.se26project.tracelab/` |

启动失败时检查该目录下的 `startup-error.log`。

### 从源码构建：通用要求

- Python 3.11 或更高版本
- [uv](https://docs.astral.sh/uv/)
- Node.js 20 或更高版本
- pnpm 9 或更高版本
- Rust 1.77.2 或更高版本

先安装 JavaScript 依赖：

```bash
cd frontend
pnpm install
```

桌面构建会先生成当前平台的运行组件，再交给 Tauri 打包。因此 macOS、Windows 和 Linux
安装包应分别在对应系统和目标 CPU 架构上构建，不要直接复制其他平台生成的运行目录。

#### macOS

额外安装 Xcode Command Line Tools：

```bash
xcode-select --install
```

开发运行与正式构建：

```bash
cd frontend
pnpm desktop:dev
pnpm desktop:build
```

产物位于：

```text
frontend/src-tauri/target/release/bundle/macos/TraceLab.app
frontend/src-tauri/target/release/bundle/dmg/TraceLab_*.dmg
```

当前 Tauri 配置支持 macOS 10.15 及以上。Apple Silicon 与 Intel 版本应在相应架构的构建
环境中分别生成。

#### Windows

在 Windows 10/11 上额外安装：

- Rust stable 的 MSVC 工具链；
- Visual Studio 2022 的“使用 C++ 的桌面开发”工作负载；
- Microsoft Edge WebView2 Runtime（系统缺失时安装）。

在 PowerShell 中开发运行：

```powershell
Set-Location frontend
pnpm install
pnpm desktop:dev
```

生成 NSIS 安装程序：

```powershell
Set-Location frontend
pnpm exec tauri build --bundles nsis
```

产物位于：

```text
frontend\src-tauri\target\release\bundle\nsis\
```

PyInstaller 构建时可能报告 `tzdata`、`pysqlite2` 或 `MySQLdb` 等可选驱动未找到。桌面端
使用内置 SQLite；只要日志继续出现 `Prepared Tauri backend runtime` 且 Tauri 编译成功，
这些提示不影响打包。

#### Linux

以 Ubuntu/Debian 为例，先安装 Tauri 2 所需系统库：

```bash
sudo apt update
sudo apt install -y \
  build-essential curl file libayatana-appindicator3-dev libssl-dev \
  librsvg2-dev libwebkit2gtk-4.1-dev libxdo-dev wget
```

开发运行：

```bash
cd frontend
pnpm install
pnpm desktop:dev
```

生成 DEB 和 AppImage：

```bash
cd frontend
pnpm exec tauri build --bundles deb,appimage
```

产物位于：

```text
frontend/src-tauri/target/release/bundle/deb/
frontend/src-tauri/target/release/bundle/appimage/
```

Fedora、Arch 等发行版需要安装对应名称的 GTK 3、WebKitGTK 4.1、OpenSSL、librsvg、
AppIndicator 和基础编译工具包。

### 连接自己的 Sync Server

桌面端默认连接项目预置的统一服务器。开发环境可在启动桌面端前覆盖服务器地址：

```bash
TRACELAB_CLOUD_UPSTREAM=https://sync.example.com pnpm desktop:dev
```

如果服务器使用自签名或私有 CA 证书，还需提供 CA 文件：

```bash
TRACELAB_CLOUD_UPSTREAM=https://sync.example.com \
TRACELAB_CLOUD_CA_FILE=/absolute/path/to/ca.pem \
pnpm desktop:dev
```

需要向普通用户分发连接私有服务器的安装包时，应在构建前将
`backend/app/desktop.py` 中的默认 `TRACELAB_CLOUD_UPSTREAM` 和随包 CA 资源改为目标部署。
`frontend/.env.desktop.local` 配置的是桌面 WebView 到本机回环地址，不是远程服务器地址，
通常不应修改。

## TraceLab Sync Server

Sync Server 只部署账号、同步、Blob、Worker 和管理员控制台，不承载桌面界面，也不执行
论文解析、代码分析或 LLM 任务。生产部署目标为 **Linux + Docker Engine + Docker Compose
plugin**。

### 平台说明

| 操作平台 | 支持方式 |
| --- | --- |
| Linux | 生产部署平台，直接运行仓库中的 `server/compose.yaml` |
| macOS | 通过终端 SSH 管理 Linux 服务器；Docker Desktop 仅建议用于本地验证 |
| Windows | 通过 PowerShell/Windows Terminal SSH 管理 Linux 服务器；Docker Desktop/WSL2 仅建议用于本地验证 |

Compose 配置使用 Linux 持久化目录、`/etc/letsencrypt` 证书目录以及 systemd 备份单元，
因此不建议把 macOS 或 Windows Docker Desktop 作为生产服务器。

从 macOS/Linux 终端或 Windows PowerShell 进入生产服务器后，后续命令完全相同：

```bash
ssh deploy@sync.example.com
cd /path/to/TraceLab/server
```

### Linux 生产部署

准备以下资源：

- 一台安装了 Docker Engine 和 Compose plugin 的 Linux 主机；
- 指向主机的域名，以及该域名的 HTTPS 证书；
- 可用的 SMTP 账号；
- 位于服务器之外的 rclone 备份目标；
- 仅向公网开放 80/443 端口。

创建持久化目录：

```bash
sudo mkdir -p /srv/tracelab/postgres /srv/tracelab/blobs /srv/tracelab/tmp
sudo chown -R 10001:10001 /srv/tracelab/blobs /srv/tracelab/tmp
```

建议分别为 PostgreSQL、Blob 和临时目录设置磁盘配额，并预留至少约 8 GB、25 GB 和 4 GB。
将证书放在 `/etc/letsencrypt/live/<SERVER_NAME>/fullchain.pem` 和 `privkey.pem`；Nginx 容器以
只读方式挂载该目录。

初始化配置：

```bash
cd server
cp .env.example .env
openssl rand -hex 32
```

将随机值填入 `CLOUD_JWT_SECRET`，再编辑 `server/.env`，至少替换以下项目：

- `PUBLIC_ORIGIN`、`ACCOUNT_LINK_ORIGIN`、`SERVER_NAME`；
- `CLOUD_JWT_SECRET` 和 `POSTGRES_PASSWORD`；
- `ALLOWED_ORIGINS`；
- SMTP 参数；
- `BACKUP_REMOTE` 和 `RCLONE_CONFIG_PATH`；
- 需要改变磁盘位置时设置 `TRACELAB_DATA_ROOT`。

首次部署先保持 `CLOUD_SYNC_FEATURE_ENABLED=false`，再运行：

```bash
docker compose --env-file .env up -d postgres
docker compose --env-file .env run --rm migrator
docker compose --env-file .env up -d api worker proxy
docker compose --env-file .env run --rm api \
  python -m tracelab_server.cli create-admin --email admin@example.com
```

检查服务：

```bash
docker compose --env-file .env ps
curl https://sync.example.com/api/v1/health
curl https://sync.example.com/api/v1/health/ready
```

确认 HTTPS、邮件、备份和恢复演练都正常后，将 `CLOUD_SYNC_FEATURE_ENABLED` 改为 `true`，
再应用配置：

```bash
docker compose --env-file .env up -d api worker
```

管理员在任意桌面平台的浏览器中访问：

```text
https://<SERVER_NAME>/admin-console/login
```

普通用户无需直接访问服务器页面；在桌面端登录后，按项目启用同步即可。Compose 只发布
Nginx 的 80/443，PostgreSQL、API 和 Worker 不发布宿主机端口。

### 更新、日志与备份

拉取新版本后，重新构建、执行显式迁移并滚动服务：

```bash
cd server
docker compose --env-file .env build migrator api worker
docker compose --env-file .env run --rm migrator
docker compose --env-file .env up -d api worker proxy
```

常用维护命令：

```bash
docker compose --env-file .env logs -f api worker proxy
docker compose --env-file .env --profile maintenance run --rm backup
```

外部恢复校验使用 `server/deploy/restore-verify.sh`。该脚本只接受空验证库和空 Blob 目录；
`server/deploy/rebuild-cloud.sh` 是显式破坏性入口，不应放入普通启动或更新流程。完整说明见
[server/README.md](server/README.md)。

## VS Code 插件

### 运行要求

- VS Code 1.85 或更高版本；
- `uv` 在 VS Code 扩展宿主的 `PATH` 中；
- 首次启用时可访问 Python 依赖源；
- 生成 Agent 追溯时需要 LLM API Key；
- 高质量论文解析需要 MinerU 官方令牌或可访问的 MinerU 服务。

VSIX 包含 TraceLab Python 源码，但不打包平台专用的 Python 虚拟环境。插件首次运行会执行
`uv sync`，在当前平台创建自己的 `.venv`。安装 `uv` 后应完全退出并重启 VS Code，使扩展
宿主读取新的 `PATH`。

使用 Remote SSH、Dev Container 或 WSL 时，插件运行在远程扩展宿主中，因此 `uv` 和网络
访问也必须在远程主机或容器内可用。

### 在各平台安装 VSIX

所有平台都可在 VS Code 中打开“扩展”视图，点击右上角 `…`，选择
“从 VSIX 安装…”，然后选择 `tracelab-vscode-0.5.0.vsix`。

macOS/Linux 也可使用：

```bash
code --install-extension ./tracelab-vscode-0.5.0.vsix --force
```

Windows PowerShell：

```powershell
code --install-extension .\tracelab-vscode-0.5.0.vsix --force
```

安装后执行“Developer: Reload Window”，或完全重启 VS Code。

### 从源码生成 VSIX

构建要求 Node.js 20+、npm、Python 3.11+、`uv`、Bash 和 Make。macOS/Linux：

```bash
make extension-build
cd vscode-extension
npx @vscode/vsce package --allow-missing-repository
```

产物位于：

```text
vscode-extension/tracelab-vscode-0.5.0.vsix
```

Windows 建议直接安装在 macOS/Linux 构建的 VSIX；虚拟环境不会进入 VSIX，因此同一文件可
安装到 Windows、macOS 和 Linux。若必须在 Windows 上打包，请使用带 `python3`、`uv` 和
Make 的 WSL 或 Git Bash 环境运行同一组命令。

### 使用流程

1. 用 VS Code 打开需要分析的代码目录；插件使用第一个工作区目录。
2. 点击活动栏中的 TraceLab 图标，选择“初始化工作区”。
3. 选择“导入论文”，再执行“解析论文”。
4. 执行“分析代码”生成符号和张量流图。
5. 在 TraceLab 侧栏保存并测试 MinerU、LLM 配置。
6. 执行“生成追溯”，在底栏查看追溯矩阵和 Agent 进度。
7. 打开论文或张量流图；点击追溯证据或图节点可跳转到对应代码。

插件产物保存在当前工作区的 `.tracelab/`：

```text
.tracelab/
  papers/       原始 PDF、Markdown 与解析资源
  analysis/     代码符号、架构和张量流图
  traces/       追溯关系与任务日志
```

LLM API Key 和 MinerU Token 保存在 VS Code `SecretStorage`，不会写入 `.tracelab/`。其他
设置保存在 VS Code 全局用户配置中。如果不希望提交生成产物，请将 `.tracelab/` 加入项目的
`.gitignore`。

运行失败时执行命令“TraceLab: 显示输出”，并依次检查：

```bash
uv --version
code --version
```

然后确认工作区可写、网络可访问依赖源，重启 VS Code 后重试。插件的详细数据结构和验收项见
[docs/vscode-extension.md](docs/vscode-extension.md)。

## 开发检查

桌面端：

```bash
cd frontend
pnpm typecheck
pnpm test:unit
```

Sync Server：

```bash
cd server
uv sync --extra dev
uv run ruff check tracelab_server tests
uv run pytest
```

VS Code 插件：

```bash
make extension-build
cd vscode-extension
npm test
```

包含真实 MinerU 和 LLM 调用的插件端到端测试：

```bash
MINERU_TOKEN=... DEEPSEEK_KEY=... ./scripts/e2e_vscode_bundled.sh
```
